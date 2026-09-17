#pragma once

#include <Arduino.h>

namespace zeep::board {

// Production wiring recovered from the known-good firmware's live GPIO
// matrix: SD=11, BCLK=12 and WS=13. The earlier replacement assigned the
// right three pins to the wrong signals and sampled clock edges as PCM.
constexpr gpio_num_t kMicData = GPIO_NUM_11;
constexpr gpio_num_t kMicBclk = GPIO_NUM_12;
constexpr gpio_num_t kMicWordSelect = GPIO_NUM_13;
constexpr gpio_num_t kI2cSda = GPIO_NUM_8;
constexpr gpio_num_t kI2cScl = GPIO_NUM_9;

// Both devices have strap-selectable addresses. Runtime identification must
// use the manufacturer protocol (OPT IDs / SHT CRC), not assume defaults.
constexpr uint8_t kSht3xAddresses[] = {0x44, 0x45};
constexpr uint8_t kOpt3001Addresses[] = {0x44, 0x45, 0x46, 0x47};
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
// The hub remains visibly alive at one packet per second. Pi-side health and
// session aggregation may downsample independently; DSP features keep their
// own ten-second window metadata.
constexpr uint32_t kPublishPeriodMs = 1000;

}  // namespace zeep::board
