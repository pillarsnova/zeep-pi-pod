#pragma once

#include <Arduino.h>
#include <Wire.h>

namespace zeep {

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
  EnvironmentReading read();

 private:
  bool writeCommand(uint8_t address, uint16_t command);
  bool readSht3x(float* temperature_c, float* humidity_rh);
  bool readOpt3001(float* lux);
  bool readRegister(uint8_t address, uint8_t reg, uint16_t* value);
  bool writeRegister(uint8_t address, uint8_t reg, uint16_t value);
  static uint8_t shtCrc(const uint8_t* data, size_t size);

  bool sht3x_present_ = false;
  bool opt3001_present_ = false;
};

}  // namespace zeep
