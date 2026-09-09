#include "environment_sensors.h"

#include "board_config.h"

namespace zeep {

namespace {

constexpr uint16_t kShtSingleShotHighRepeatability = 0x2400;
constexpr uint8_t kOptResultRegister = 0x00;
constexpr uint8_t kOptConfigurationRegister = 0x01;
constexpr uint8_t kOptManufacturerRegister = 0x7E;
constexpr uint16_t kOptManufacturerId = 0x5449;
constexpr uint16_t kOptContinuousAutomatic800Ms = 0xCE10;

}  // namespace

bool EnvironmentSensors::begin() {
  Wire.begin(board::kI2cSda, board::kI2cScl, board::kI2cClockHz);

  uint16_t manufacturer_id = 0;
  opt3001_present_ = readRegister(
      board::kOpt3001Address,
      kOptManufacturerRegister,
      &manufacturer_id);
  opt3001_present_ = opt3001_present_ &&
                     manufacturer_id == kOptManufacturerId &&
                     writeRegister(
                         board::kOpt3001Address,
                         kOptConfigurationRegister,
                         kOptContinuousAutomatic800Ms);

  sht3x_present_ = writeCommand(board::kSht3xAddress, 0x30A2);
  delay(3);
  return sht3x_present_ || opt3001_present_;
}

EnvironmentReading EnvironmentSensors::read() {
  EnvironmentReading reading;
  reading.sht3x_ok = sht3x_present_ && readSht3x(
      &reading.temperature_c,
      &reading.humidity_rh);
  reading.opt3001_ok = opt3001_present_ && readOpt3001(&reading.lux);
  return reading;
}

bool EnvironmentSensors::writeCommand(uint8_t address, uint16_t command) {
  Wire.beginTransmission(address);
  Wire.write(static_cast<uint8_t>(command >> 8));
  Wire.write(static_cast<uint8_t>(command & 0xFF));
  return Wire.endTransmission() == 0;
}

bool EnvironmentSensors::readSht3x(
    float* temperature_c,
    float* humidity_rh) {
  if (!writeCommand(board::kSht3xAddress, kShtSingleShotHighRepeatability)) {
    return false;
  }
  delay(20);
  constexpr size_t kResponseBytes = 6;
  const size_t received = Wire.requestFrom(
      static_cast<int>(board::kSht3xAddress),
      static_cast<int>(kResponseBytes));
  if (received != kResponseBytes) {
    return false;
  }

  uint8_t data[kResponseBytes];
  for (size_t index = 0; index < kResponseBytes; ++index) {
    data[index] = Wire.read();
  }
  if (shtCrc(data, 2) != data[2] || shtCrc(data + 3, 2) != data[5]) {
    return false;
  }

  const uint16_t raw_temperature = (data[0] << 8) | data[1];
  const uint16_t raw_humidity = (data[3] << 8) | data[4];
  *temperature_c = -45.0F + 175.0F * raw_temperature / 65535.0F;
  *humidity_rh = 100.0F * raw_humidity / 65535.0F;
  return isfinite(*temperature_c) && isfinite(*humidity_rh);
}

bool EnvironmentSensors::readOpt3001(float* lux) {
  uint16_t raw = 0;
  if (!readRegister(board::kOpt3001Address, kOptResultRegister, &raw)) {
    return false;
  }
  const uint16_t exponent = (raw >> 12) & 0x0F;
  const uint16_t mantissa = raw & 0x0FFF;
  *lux = 0.01F * static_cast<float>(1U << exponent) * mantissa;
  return isfinite(*lux) && *lux >= 0.0F;
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
