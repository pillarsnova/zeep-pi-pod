#pragma once

#include <Arduino.h>

namespace zeep::board {

// Wiring verified against the currently installed Sensor Hub 1 harness.
constexpr gpio_num_t kMicBclk = GPIO_NUM_11;
constexpr gpio_num_t kMicWordSelect = GPIO_NUM_12;
constexpr gpio_num_t kMicData = GPIO_NUM_13;
constexpr gpio_num_t kI2cSda = GPIO_NUM_8;
constexpr gpio_num_t kI2cScl = GPIO_NUM_9;

constexpr uint8_t kSht3xAddress = 0x45;
constexpr uint8_t kOpt3001Address = 0x44;
constexpr uint32_t kI2cClockHz = 400000;

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kPublishPeriodMs = 10000;

}  // namespace zeep::board
