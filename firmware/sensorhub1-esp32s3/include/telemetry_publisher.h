#pragma once

#include <Arduino.h>

#include "audio_meter.h"
#include "environment_sensors.h"

namespace zeep {

// Owns the Sensor Hub 1 wire contract and its fixed publication cadence.
// Sensor acquisition remains independent: a failure in one device is
// represented in that sensor's status and never suppresses the other two.
class TelemetryPublisher {
 public:
  TelemetryPublisher(
      AudioMeter& audio_meter,
      EnvironmentSensors& environment_sensors);

  void begin(uint32_t boot_id);
  void recordSoundWindow(const SoundWindow& sound);
  void publishBootStatus(const char* event = "boot");
  void publishInitialTelemetry();
  void publishIfDue(uint32_t now_ms);
  void handleCommand(String command);

 private:
  void publishTelemetry(uint32_t now_ms);
  void publishCalibrationResponse(bool accepted);
  static bool parseFiniteFloat(const String& token, float* output);

  AudioMeter& audio_meter_;
  EnvironmentSensors& environment_sensors_;
  SoundWindow latest_sound_;
  bool has_sound_window_ = false;
  uint32_t telemetry_sequence_ = 0;
  uint32_t last_publish_ms_ = 0;
  uint32_t boot_id_ = 0;
};

}  // namespace zeep
