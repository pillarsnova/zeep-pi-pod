#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace zeep {

struct SensorHealthSnapshot {
  uint8_t address = 0;
  bool present = false;
  bool measurement_valid = false;
  bool fresh = false;
  bool last_attempt_ok = false;
  const char* state = "initializing";
  const char* reason = "not_started";
  uint32_t age_ms = UINT32_MAX;
  uint32_t last_success_ms = 0;
  uint32_t consecutive_failures = 0;
  uint32_t total_failures = 0;
  uint32_t recovery_count = 0;
};

struct Sht3xSnapshot {
  SensorHealthSnapshot health;
  float temperature_c = NAN;
  float humidity_rh = NAN;
};

struct Opt3001Snapshot {
  SensorHealthSnapshot health;
  float lux = NAN;
};

struct EnvironmentSnapshot {
  Sht3xSnapshot sht3x;
  Opt3001Snapshot opt3001;
  bool i2c_bus_ready = false;
  uint32_t i2c_recovery_count = 0;
  uint32_t captured_ms = 0;
};

// Compatibility view for the existing flat Sensor Hub 1 packet. New code
// should use snapshot() so diagnostics are not discarded.
struct EnvironmentReading {
  bool sht3x_ok = false;
  bool opt3001_ok = false;
  float temperature_c = NAN;
  float humidity_rh = NAN;
  float lux = NAN;
};

class EnvironmentSensors {
 public:
  bool begin();
  void poll(uint32_t now_ms);
  EnvironmentSnapshot snapshot(uint32_t now_ms) const;
  EnvironmentReading read();

 private:
  struct SensorRuntime {
    bool present = false;
    bool configured = false;
    bool has_measurement = false;
    bool last_attempt_ok = false;
    const char* reason = "not_started";
    uint32_t last_success_ms = 0;
    uint32_t next_reprobe_ms = 0;
    uint32_t consecutive_failures = 0;
    uint32_t total_failures = 0;
    uint32_t recovery_count = 0;
  };

  void probeSht3x(uint32_t now_ms);
  void probeOpt3001(uint32_t now_ms);
  void pollSht3x(uint32_t now_ms);
  void pollOpt3001(uint32_t now_ms);
  void recoverI2cBus(uint32_t now_ms);
  void recordSuccess(SensorRuntime* runtime, uint32_t now_ms);
  void recordFailure(
      SensorRuntime* runtime,
      const char* reason,
      uint32_t now_ms);
  SensorHealthSnapshot healthSnapshot(
      const SensorRuntime& runtime,
      uint8_t address,
      uint32_t now_ms) const;
  bool writeCommand(uint8_t address, uint16_t command);
  bool readSht3x(
      float* temperature_c,
      float* humidity_rh,
      const char** reason);
  bool readOpt3001(float* lux, const char** reason);
  bool readRegister(uint8_t address, uint8_t reg, uint16_t* value);
  bool writeRegister(uint8_t address, uint8_t reg, uint16_t value);
  static uint8_t shtCrc(const uint8_t* data, size_t size);

  bool bus_ready_ = false;
  bool poll_started_ = false;
  uint32_t last_poll_ms_ = 0;
  uint32_t next_bus_recovery_ms_ = 0;
  uint32_t i2c_recovery_count_ = 0;
  SensorRuntime sht3x_runtime_;
  SensorRuntime opt3001_runtime_;
  float temperature_c_ = NAN;
  float humidity_rh_ = NAN;
  float lux_ = NAN;
};

}  // namespace zeep
