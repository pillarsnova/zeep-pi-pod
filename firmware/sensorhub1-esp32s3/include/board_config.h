#pragma once

#include <Arduino.h>

namespace zeep::board {

// Released Sensor Hub 1 harness contract. Logical pin mapping is verified in
// software; Production still requires continuity and waveform acceptance on
// the physical board before this candidate may be promoted.
constexpr gpio_num_t kMicBclk = GPIO_NUM_11;
constexpr gpio_num_t kMicWordSelect = GPIO_NUM_12;
constexpr gpio_num_t kMicData = GPIO_NUM_13;
constexpr gpio_num_t kI2cSda = GPIO_NUM_8;
constexpr gpio_num_t kI2cScl = GPIO_NUM_9;

constexpr uint8_t kSht3xAddress = 0x45;
constexpr uint8_t kOpt3001Address = 0x44;
constexpr uint32_t kI2cClockHz = 400000;
constexpr uint16_t kI2cTransactionTimeoutMs = 50;

// Environment sensors are sampled independently from the 10-second USB
// telemetry cadence. A cached value is no longer considered current after
// three missed sample opportunities.
constexpr uint32_t kEnvironmentPollPeriodMs = 2000;
constexpr uint32_t kEnvironmentFreshnessMs = 6000;
constexpr uint32_t kEnvironmentReprobePeriodMs = 10000;
constexpr uint32_t kI2cBusRecoveryPeriodMs = 30000;
constexpr uint8_t kEnvironmentFailuresBeforeReprobe = 3;

constexpr uint32_t kSerialBaud = 115200;
constexpr uint32_t kPublishPeriodMs = 10000;

}  // namespace zeep::board
