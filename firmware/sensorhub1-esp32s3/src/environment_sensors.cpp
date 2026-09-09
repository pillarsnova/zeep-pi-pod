#include "environment_sensors.h"

#include "board_config.h"

namespace zeep {

namespace {

constexpr uint16_t kShtSingleShotHighRepeatability = 0x2400;
constexpr uint8_t kOptResultRegister = 0x00;
constexpr uint8_t kOptConfigurationRegister = 0x01;
constexpr uint8_t kOptManufacturerRegister = 0x7E;
constexpr uint8_t kOptDeviceIdRegister = 0x7F;
constexpr uint16_t kOptManufacturerId = 0x5449;
constexpr uint16_t kOptDeviceId = 0x3001;
constexpr uint16_t kOptContinuousAutomatic800Ms = 0xCE10;
// OVF, CRF, FH and FL (bits 8..5) are read-only status flags and may change
// between write and readback transactions. Compare only writable fields.
constexpr uint16_t kOptWritableConfigMask = 0xFE1F;
constexpr float kShtMinimumTemperatureC = -40.0F;
constexpr float kShtMaximumTemperatureC = 125.0F;
constexpr float kShtMinimumHumidityRh = 0.0F;
constexpr float kShtMaximumHumidityRh = 100.0F;
constexpr float kOptMaximumLux = 83865.6F;

bool timeReached(uint32_t now_ms, uint32_t deadline_ms) {
  return static_cast<int32_t>(now_ms - deadline_ms) >= 0;
}

uint32_t measurementAge(uint32_t now_ms, uint32_t last_success_ms) {
  return now_ms - last_success_ms;
}

}  // namespace

bool EnvironmentSensors::begin() {
  bus_ready_ = Wire.begin(
      board::kI2cSda,
      board::kI2cScl,
      board::kI2cClockHz);

  const uint32_t now_ms = millis();
  if (!bus_ready_) {
    sht3x_runtime_.reason = "i2c_begin_failed";
    opt3001_runtime_.reason = "i2c_begin_failed";
    next_bus_recovery_ms_ =
        now_ms + board::kI2cBusRecoveryPeriodMs;
    return false;
  }
  Wire.setTimeOut(board::kI2cTransactionTimeoutMs);

  probeSht3x(now_ms);
  probeOpt3001(millis());
  last_poll_ms_ = millis();
  poll_started_ = true;

  // A healthy bus is enough to start the runtime. Missing devices are
  // re-probed independently instead of preventing the hub from starting.
  return true;
}

void EnvironmentSensors::poll(uint32_t now_ms) {
  if (!bus_ready_) {
    if (timeReached(now_ms, next_bus_recovery_ms_)) {
      recoverI2cBus(now_ms);
    }
    return;
  }
  if (poll_started_ &&
      now_ms - last_poll_ms_ < board::kEnvironmentPollPeriodMs) {
    return;
  }

  poll_started_ = true;
  last_poll_ms_ = now_ms;
  pollSht3x(now_ms);
  pollOpt3001(millis());
  if (!sht3x_runtime_.configured && !opt3001_runtime_.configured &&
      timeReached(millis(), next_bus_recovery_ms_)) {
    recoverI2cBus(millis());
  }
}

EnvironmentSnapshot EnvironmentSensors::snapshot(uint32_t now_ms) const {
  EnvironmentSnapshot result;
  result.captured_ms = now_ms;
  result.i2c_bus_ready = bus_ready_;
  result.i2c_recovery_count = i2c_recovery_count_;
  result.sht3x.health = healthSnapshot(
      sht3x_runtime_, board::kSht3xAddress, now_ms);
  result.opt3001.health = healthSnapshot(
      opt3001_runtime_, board::kOpt3001Address, now_ms);

  if (result.sht3x.health.measurement_valid &&
      result.sht3x.health.fresh) {
    result.sht3x.temperature_c = temperature_c_;
    result.sht3x.humidity_rh = humidity_rh_;
  }
  if (result.opt3001.health.measurement_valid &&
      result.opt3001.health.fresh) {
    result.opt3001.lux = lux_;
  }
  return result;
}

EnvironmentReading EnvironmentSensors::read() {
  const uint32_t now_ms = millis();
  poll(now_ms);
  const EnvironmentSnapshot current = snapshot(millis());
  EnvironmentReading reading;
  reading.sht3x_ok = current.sht3x.health.measurement_valid &&
                     current.sht3x.health.fresh;
  reading.opt3001_ok = current.opt3001.health.measurement_valid &&
                       current.opt3001.health.fresh;
  reading.temperature_c = current.sht3x.temperature_c;
  reading.humidity_rh = current.sht3x.humidity_rh;
  reading.lux = current.opt3001.lux;
  return reading;
}

void EnvironmentSensors::probeSht3x(uint32_t now_ms) {
  sht3x_runtime_.last_attempt_ok = false;
  if (!writeCommand(board::kSht3xAddress, 0x30A2)) {
    sht3x_runtime_.present = false;
    sht3x_runtime_.configured = false;
    recordFailure(&sht3x_runtime_, "sht_probe_failed", now_ms);
    return;
  }

  delay(3);
  float temperature_c = NAN;
  float humidity_rh = NAN;
  const char* reason = "sht_read_failed";
  if (!readSht3x(&temperature_c, &humidity_rh, &reason)) {
    sht3x_runtime_.present = false;
    sht3x_runtime_.configured = false;
    recordFailure(&sht3x_runtime_, reason, millis());
    return;
  }

  sht3x_runtime_.present = true;
  sht3x_runtime_.configured = true;
  temperature_c_ = temperature_c;
  humidity_rh_ = humidity_rh;
  recordSuccess(&sht3x_runtime_, millis());
}

void EnvironmentSensors::probeOpt3001(uint32_t now_ms) {
  opt3001_runtime_.last_attempt_ok = false;
  uint16_t manufacturer_id = 0;
  uint16_t device_id = 0;
  if (!readRegister(
          board::kOpt3001Address,
          kOptManufacturerRegister,
          &manufacturer_id) ||
      !readRegister(
          board::kOpt3001Address,
          kOptDeviceIdRegister,
          &device_id)) {
    opt3001_runtime_.present = false;
    opt3001_runtime_.configured = false;
    recordFailure(
        &opt3001_runtime_, "opt_identity_read_failed", now_ms);
    return;
  }
  if (manufacturer_id != kOptManufacturerId || device_id != kOptDeviceId) {
    opt3001_runtime_.present = false;
    opt3001_runtime_.configured = false;
    recordFailure(
        &opt3001_runtime_, "opt_identity_mismatch", now_ms);
    return;
  }

  opt3001_runtime_.present = true;
  uint16_t config_readback = 0;
  const bool configured = writeRegister(
      board::kOpt3001Address,
      kOptConfigurationRegister,
      kOptContinuousAutomatic800Ms);
  const bool readback_ok = configured && readRegister(
      board::kOpt3001Address,
      kOptConfigurationRegister,
      &config_readback);
  const bool config_matches = readback_ok &&
      (config_readback & kOptWritableConfigMask) ==
          (kOptContinuousAutomatic800Ms & kOptWritableConfigMask);
  if (!config_matches) {
    opt3001_runtime_.configured = false;
    recordFailure(
        &opt3001_runtime_, "opt_config_readback_failed", now_ms);
    return;
  }

  opt3001_runtime_.configured = true;
  opt3001_runtime_.last_attempt_ok = true;
  opt3001_runtime_.reason = "warming_up";
  opt3001_runtime_.next_reprobe_ms = 0;
}

void EnvironmentSensors::pollSht3x(uint32_t now_ms) {
  if (!sht3x_runtime_.configured) {
    if (timeReached(now_ms, sht3x_runtime_.next_reprobe_ms)) {
      probeSht3x(now_ms);
    }
    return;
  }

  float temperature_c = NAN;
  float humidity_rh = NAN;
  const char* reason = "sht_read_failed";
  if (!readSht3x(&temperature_c, &humidity_rh, &reason)) {
    recordFailure(&sht3x_runtime_, reason, now_ms);
    return;
  }

  temperature_c_ = temperature_c;
  humidity_rh_ = humidity_rh;
  recordSuccess(&sht3x_runtime_, millis());
}

void EnvironmentSensors::pollOpt3001(uint32_t now_ms) {
  if (!opt3001_runtime_.configured) {
    if (timeReached(now_ms, opt3001_runtime_.next_reprobe_ms)) {
      probeOpt3001(now_ms);
    }
    return;
  }

  float lux = NAN;
  const char* reason = "opt_read_failed";
  if (!readOpt3001(&lux, &reason)) {
    recordFailure(&opt3001_runtime_, reason, now_ms);
    return;
  }

  lux_ = lux;
  recordSuccess(&opt3001_runtime_, millis());
}

void EnvironmentSensors::recoverI2cBus(uint32_t now_ms) {
  // A shared-bus reset is intentionally reserved for the case where both
  // devices are unavailable. A fault in one sensor must not disturb the
  // healthy peer.
  Wire.end();
  delay(1);
  bus_ready_ = Wire.begin(
      board::kI2cSda,
      board::kI2cScl,
      board::kI2cClockHz);
  ++i2c_recovery_count_;
  next_bus_recovery_ms_ =
      now_ms + board::kI2cBusRecoveryPeriodMs;

  if (!bus_ready_) {
    sht3x_runtime_.reason = "i2c_recovery_failed";
    opt3001_runtime_.reason = "i2c_recovery_failed";
    return;
  }

  Wire.setTimeOut(board::kI2cTransactionTimeoutMs);
  sht3x_runtime_.next_reprobe_ms = now_ms;
  opt3001_runtime_.next_reprobe_ms = now_ms;
  sht3x_runtime_.reason = "i2c_bus_recovered";
  opt3001_runtime_.reason = "i2c_bus_recovered";
}

void EnvironmentSensors::recordSuccess(
    SensorRuntime* runtime,
    uint32_t now_ms) {
  if (runtime->total_failures > 0 && runtime->consecutive_failures > 0) {
    ++runtime->recovery_count;
  }
  runtime->present = true;
  runtime->configured = true;
  runtime->has_measurement = true;
  runtime->last_attempt_ok = true;
  runtime->last_success_ms = now_ms;
  runtime->next_reprobe_ms = 0;
  runtime->consecutive_failures = 0;
  runtime->reason = "ok";
}

void EnvironmentSensors::recordFailure(
    SensorRuntime* runtime,
    const char* reason,
    uint32_t now_ms) {
  runtime->last_attempt_ok = false;
  runtime->reason = reason;
  ++runtime->consecutive_failures;
  ++runtime->total_failures;

  if (runtime->consecutive_failures >=
      board::kEnvironmentFailuresBeforeReprobe) {
    runtime->present = false;
    runtime->configured = false;
    runtime->next_reprobe_ms =
        now_ms + board::kEnvironmentReprobePeriodMs;
  }
}

SensorHealthSnapshot EnvironmentSensors::healthSnapshot(
    const SensorRuntime& runtime,
    uint8_t address,
    uint32_t now_ms) const {
  SensorHealthSnapshot health;
  health.address = address;
  health.present = runtime.present;
  health.measurement_valid = runtime.has_measurement &&
                             runtime.present &&
                             runtime.configured;
  health.last_attempt_ok = runtime.last_attempt_ok;
  health.last_success_ms = runtime.last_success_ms;
  health.consecutive_failures = runtime.consecutive_failures;
  health.total_failures = runtime.total_failures;
  health.recovery_count = runtime.recovery_count;

  if (runtime.has_measurement) {
    health.age_ms = measurementAge(now_ms, runtime.last_success_ms);
    health.fresh = health.age_ms <= board::kEnvironmentFreshnessMs;
  }

  if (!bus_ready_) {
    health.state = "unavailable";
    health.reason = runtime.reason;
  } else if (!runtime.present || !runtime.configured) {
    health.state = "recovering";
    health.reason = runtime.reason;
  } else if (!runtime.has_measurement) {
    health.state = "initializing";
    health.reason = runtime.reason;
  } else if (!health.fresh) {
    health.state = "degraded";
    health.reason = runtime.has_measurement ? "stale" : runtime.reason;
  } else if (!runtime.last_attempt_ok) {
    health.state = "degraded";
    health.reason = runtime.reason;
  } else {
    health.state = "ready";
    health.reason = "ok";
  }
  return health;
}

bool EnvironmentSensors::writeCommand(uint8_t address, uint16_t command) {
  Wire.beginTransmission(address);
  Wire.write(static_cast<uint8_t>(command >> 8));
  Wire.write(static_cast<uint8_t>(command & 0xFF));
  return Wire.endTransmission() == 0;
}

bool EnvironmentSensors::readSht3x(
    float* temperature_c,
    float* humidity_rh,
    const char** reason) {
  if (!writeCommand(board::kSht3xAddress, kShtSingleShotHighRepeatability)) {
    *reason = "sht_command_failed";
    return false;
  }
  delay(20);
  constexpr size_t kResponseBytes = 6;
  const size_t received = Wire.requestFrom(
      static_cast<int>(board::kSht3xAddress),
      static_cast<int>(kResponseBytes));
  if (received != kResponseBytes) {
    while (Wire.available()) {
      Wire.read();
    }
    *reason = "sht_short_read";
    return false;
  }

  uint8_t data[kResponseBytes];
  for (size_t index = 0; index < kResponseBytes; ++index) {
    data[index] = Wire.read();
  }
  if (shtCrc(data, 2) != data[2] || shtCrc(data + 3, 2) != data[5]) {
    *reason = "sht_crc_failed";
    return false;
  }

  const uint16_t raw_temperature = (data[0] << 8) | data[1];
  const uint16_t raw_humidity = (data[3] << 8) | data[4];
  *temperature_c = -45.0F + 175.0F * raw_temperature / 65535.0F;
  *humidity_rh = 100.0F * raw_humidity / 65535.0F;
  const bool in_range = isfinite(*temperature_c) &&
      isfinite(*humidity_rh) &&
      *temperature_c >= kShtMinimumTemperatureC &&
      *temperature_c <= kShtMaximumTemperatureC &&
      *humidity_rh >= kShtMinimumHumidityRh &&
      *humidity_rh <= kShtMaximumHumidityRh;
  if (!in_range) {
    *reason = "sht_out_of_range";
  }
  return in_range;
}

bool EnvironmentSensors::readOpt3001(float* lux, const char** reason) {
  uint16_t configuration = 0;
  if (!readRegister(
          board::kOpt3001Address,
          kOptConfigurationRegister,
          &configuration)) {
    *reason = "opt_config_read_failed";
    return false;
  }
  if ((configuration & kOptWritableConfigMask) !=
      (kOptContinuousAutomatic800Ms & kOptWritableConfigMask)) {
    *reason = "opt_config_changed";
    return false;
  }
  if ((configuration & 0x0100U) != 0) {
    *reason = "opt_overflow";
    return false;
  }

  uint16_t raw = 0;
  if (!readRegister(board::kOpt3001Address, kOptResultRegister, &raw)) {
    *reason = "opt_result_read_failed";
    return false;
  }
  const uint16_t exponent = (raw >> 12) & 0x0F;
  const uint16_t mantissa = raw & 0x0FFF;
  *lux = 0.01F * static_cast<float>(1U << exponent) * mantissa;
  const bool in_range = isfinite(*lux) &&
      *lux >= 0.0F && *lux <= kOptMaximumLux;
  if (!in_range) {
    *reason = "opt_out_of_range";
  }
  return in_range;
}

bool EnvironmentSensors::readRegister(
    uint8_t address,
    uint8_t reg,
    uint16_t* value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(static_cast<int>(address), 2) != 2) {
    while (Wire.available()) {
      Wire.read();
    }
    return false;
  }
  *value = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
  return true;
}

bool EnvironmentSensors::writeRegister(
    uint8_t address,
    uint8_t reg,
    uint16_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(static_cast<uint8_t>(value >> 8));
  Wire.write(static_cast<uint8_t>(value & 0xFF));
  return Wire.endTransmission() == 0;
}

uint8_t EnvironmentSensors::shtCrc(const uint8_t* data, size_t size) {
  uint8_t crc = 0xFF;
  for (size_t index = 0; index < size; ++index) {
    crc ^= data[index];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : crc << 1;
    }
  }
  return crc;
}

}  // namespace zeep
