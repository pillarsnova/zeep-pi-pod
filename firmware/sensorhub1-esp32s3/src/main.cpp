#include <Arduino.h>
#include <ArduinoJson.h>

#include "audio_meter.h"
#include "board_config.h"
#include "environment_sensors.h"

#ifndef ZEEP_FIRMWARE_VERSION
#define ZEEP_FIRMWARE_VERSION "sensorhub1-development"
#endif

namespace {

zeep::AudioMeter audio_meter;
zeep::EnvironmentSensors environment_sensors;
uint32_t sequence_number = 0;
uint32_t last_fallback_publish_ms = 0;

void addNumberOrNull(JsonObject object, const char* key, float value) {
  if (isfinite(value)) {
    object[key] = value;
  } else {
    object[key] = nullptr;
  }
}

void publishTelemetry(const zeep::SoundWindow& sound) {
  const zeep::EnvironmentReading environment = environment_sensors.read();
  JsonDocument document;
  document["schema_version"] = 1;
  document["event"] = "environment";
  document["source"] = "sensorhub1_firmware";
  document["hub_id"] = "sensorhub1";
  document["firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["sound_firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["sequence"] = ++sequence_number;
  document["monotonic_ms"] = millis();

  addNumberOrNull(document.as<JsonObject>(), "temperature_c",
                  environment.temperature_c);
  addNumberOrNull(document.as<JsonObject>(), "humidity_rh",
                  environment.humidity_rh);
  addNumberOrNull(document.as<JsonObject>(), "lux", environment.lux);
  addNumberOrNull(document.as<JsonObject>(), "sound_rms", sound.rms);
  addNumberOrNull(document.as<JsonObject>(), "sound_peak", sound.peak);
  addNumberOrNull(document.as<JsonObject>(), "sound_dbfs", sound.dbfs);
  addNumberOrNull(
      document.as<JsonObject>(),
      "sound_a_weighted_dbfs",
      sound.a_weighted_dbfs);
  addNumberOrNull(
      document.as<JsonObject>(),
      "sound_laeq_dba",
      sound.laeq_dba);
  document["sound_valid"] = sound.valid;
  document["sound_weighting"] = "A";
  document["sound_metric"] = "LAeq";
  document["sound_window_ms"] = sound.window_ms;
  document["sound_wall_window_ms"] = sound.wall_window_ms;
  document["sound_samples"] = sound.sample_count;
  document["sound_sample_rate_hz"] = 48000;
  document["sound_calibration_offset_db"] =
      sound.calibration_offset_db;
  document["sound_clipped_samples"] = sound.clipped_samples;
  document["sound_zero_samples"] = sound.zero_samples;
  document["sound_read_errors"] = sound.read_errors;
  if (sound.invalid_reason != nullptr) {
    document["sound_invalid_reason"] = sound.invalid_reason;
  }

  JsonObject status = document["sensor_status"].to<JsonObject>();
  status["sht3x_dis"] = environment.sht3x_ok;
  status["opt3001"] = environment.opt3001_ok;
  status["sph0645"] = audio_meter.healthy();
  serializeJson(document, Serial);
  Serial.println();
}

void publishBootStatus() {
  JsonDocument document;
  document["schema_version"] = 1;
  document["event"] = "boot";
  document["source"] = "sensorhub1_firmware";
  document["hub_id"] = "sensorhub1";
  document["firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["chip_model"] = ESP.getChipModel();
  document["flash_bytes"] = ESP.getFlashChipSize();
  document["psram_bytes"] = ESP.getPsramSize();
  document["sound_calibration_offset_db"] = audio_meter.calibrationOffset();
  serializeJson(document, Serial);
  Serial.println();
}

void publishInvalidFallback() {
  zeep::SoundWindow unavailable;
  unavailable.ready = true;
  unavailable.invalid_reason = "microphone_unavailable";
  unavailable.window_ms = zeep::board::kPublishPeriodMs;
  unavailable.calibration_offset_db = audio_meter.calibrationOffset();
  publishTelemetry(unavailable);
}

void handleCommand(String command) {
  command.trim();
  if (command == "INFO") {
    publishBootStatus();
    return;
  }
  if (command == "CAL SOUND RESET") {
    audio_meter.setCalibrationOffset(0.0F);
    publishBootStatus();
    return;
  }
  constexpr const char* kPrefix = "CAL SOUND OFFSET ";
  if (command.startsWith(kPrefix)) {
    const float value = command.substring(strlen(kPrefix)).toFloat();
    JsonDocument response;
    response["event"] = "calibration_response";
    response["accepted"] = audio_meter.setCalibrationOffset(value);
    response["sound_calibration_offset_db"] =
        audio_meter.calibrationOffset();
    serializeJson(response, Serial);
    Serial.println();
  }
}

}  // namespace

void setup() {
  Serial.begin(zeep::board::kSerialBaud);
  delay(1000);
  environment_sensors.begin();
  audio_meter.begin();
}

void loop() {
  zeep::SoundWindow sound;
  if (audio_meter.takeWindow(&sound)) {
    publishTelemetry(sound);
  } else if (!audio_meter.healthy() &&
             millis() - last_fallback_publish_ms >=
                 zeep::board::kPublishPeriodMs) {
    last_fallback_publish_ms = millis();
    publishInvalidFallback();
  }

  if (Serial.available()) {
    handleCommand(Serial.readStringUntil('\n'));
  }
  delay(5);
}
