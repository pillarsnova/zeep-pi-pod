#include "telemetry_publisher.h"

#include <ArduinoJson.h>

#include <cerrno>
#include <cstdlib>

#include "board_config.h"

#ifndef ZEEP_FIRMWARE_VERSION
#define ZEEP_FIRMWARE_VERSION "sensorhub1-integrated-development"
#endif

namespace {

constexpr const char* kTelemetrySchema = "zeep.sensor.telemetry";
constexpr const char* kTelemetryVersion = "1.0";
constexpr uint32_t kSoundWindowFreshMs = 15000;

bool deadlineElapsed(
    uint32_t now_ms,
    uint32_t previous_ms,
    uint32_t period_ms) {
  return now_ms - previous_ms >= period_ms;
}

void addNumberOrNull(JsonObject object, const char* key, float value) {
  if (isfinite(value)) {
    object[key] = value;
  } else {
    object[key] = nullptr;
  }
}

void addAgeOrNull(JsonObject object, uint32_t age_ms) {
  if (age_ms == UINT32_MAX) {
    object["age_ms"] = nullptr;
  } else {
    object["age_ms"] = age_ms;
  }
}

void addSensorHealth(
    JsonObject object,
    const zeep::SensorHealthSnapshot& health) {
  char address[5];
  snprintf(address, sizeof(address), "0x%02X", health.address);
  object["state"] = health.state;
  object["reason"] = health.reason;
  object["address"] = address;
  object["present"] = health.present;
  object["measurement_valid"] = health.measurement_valid;
  object["fresh"] = health.fresh;
  object["last_attempt_ok"] = health.last_attempt_ok;
  addAgeOrNull(object, health.age_ms);
  object["consecutive_failures"] = health.consecutive_failures;
  object["total_failures"] = health.total_failures;
  object["recovery_count"] = health.recovery_count;
}

bool environmentUsable(const zeep::SensorHealthSnapshot& health) {
  return health.measurement_valid && health.fresh;
}

const char* environmentPacketStatus(
    const zeep::SensorHealthSnapshot& health) {
  if (!environmentUsable(health)) {
    return strcmp(health.state, "recovering") == 0
        ? "recovering" : "invalid";
  }
  return health.last_attempt_ok && strcmp(health.state, "ready") == 0
      ? "live" : "degraded";
}

void addSht3xTelemetry(
    JsonObject sensors,
    JsonObject diagnostics,
    const zeep::Sht3xSnapshot& snapshot) {
  const bool usable = environmentUsable(snapshot.health);
  JsonObject sensor = sensors["sht3x_dis"].to<JsonObject>();
  sensor["status"] = environmentPacketStatus(snapshot.health);
  sensor["reason"] = snapshot.health.reason;
  addAgeOrNull(sensor, snapshot.health.age_ms);
  JsonObject values = sensor["values"].to<JsonObject>();
  addNumberOrNull(
      values,
      "temperature_c",
      usable ? snapshot.temperature_c : NAN);
  addNumberOrNull(
      values,
      "humidity_rh",
      usable ? snapshot.humidity_rh : NAN);
  addSensorHealth(
      diagnostics["sht3x_dis"].to<JsonObject>(),
      snapshot.health);
  addSensorHealth(sensor["diagnostics"].to<JsonObject>(), snapshot.health);
}

void addOpt3001Telemetry(
    JsonObject sensors,
    JsonObject diagnostics,
    const zeep::Opt3001Snapshot& snapshot) {
  const bool usable = environmentUsable(snapshot.health);
  JsonObject sensor = sensors["opt3001"].to<JsonObject>();
  sensor["status"] = environmentPacketStatus(snapshot.health);
  sensor["reason"] = snapshot.health.reason;
  addAgeOrNull(sensor, snapshot.health.age_ms);
  JsonObject values = sensor["values"].to<JsonObject>();
  addNumberOrNull(values, "lux", usable ? snapshot.lux : NAN);
  addSensorHealth(
      diagnostics["opt3001"].to<JsonObject>(),
      snapshot.health);
  addSensorHealth(sensor["diagnostics"].to<JsonObject>(), snapshot.health);
}

void addSoundTelemetry(
    JsonObject sensors,
    JsonObject diagnostics,
    const zeep::SoundWindow& sound,
    const zeep::AudioHealth& health,
    uint32_t now_ms) {
  JsonObject sensor = sensors["sph0645"].to<JsonObject>();
  const bool stream_live = health.driver_ready && health.task_running &&
      health.stream_active;
  const bool measurement_live = sound.valid && stream_live;
  const bool measurement_held = sound.valid && !stream_live;
  sensor["status"] = measurement_live ? "live" :
      (measurement_held ? "held" :
       (stream_live ? "invalid" : "recovering"));
  JsonObject values = sensor["values"].to<JsonObject>();
  addNumberOrNull(values, "sound_rms", sound.rms);
  addNumberOrNull(values, "sound_peak", sound.peak);
  addNumberOrNull(values, "sound_dbfs", sound.dbfs);
  addNumberOrNull(
      values,
      "sound_a_weighted_dbfs",
      sound.a_weighted_dbfs);
  addNumberOrNull(values, "sound_laeq_dba", sound.laeq_dba);
  values["sound_valid"] = sound.valid;
  values["sound_weighting"] = "A";
  values["sound_metric"] = "LAeq";
  values["sound_window_ms"] = sound.window_ms;
  values["sound_wall_window_ms"] = sound.wall_window_ms;
  values["sound_samples"] = sound.sample_count;
  values["sound_sample_rate_hz"] = 48000;
  values["sound_calibration_offset_db"] = sound.calibration_offset_db;
  values["sound_clipped_samples"] = sound.clipped_samples;
  values["sound_zero_samples"] = sound.zero_samples;
  values["sound_repeated_samples"] = sound.repeated_samples;
  values["sound_read_errors"] = sound.read_errors;
  values["sound_window_sequence"] = sound.sequence;
  const char* invalid_reason =
      sound.invalid_reason == nullptr ? "unknown" : sound.invalid_reason;
  const char* sensor_reason = measurement_live ? "ok" :
      (measurement_held ? health.reason : invalid_reason);
  sensor["reason"] = sensor_reason;
  if (sound.completed_ms == 0) {
    sensor["age_ms"] = nullptr;
  } else {
    sensor["age_ms"] = now_ms - sound.completed_ms;
  }
  if (!sound.valid) {
    values["sound_invalid_reason"] = invalid_reason;
  }

  JsonObject detail = diagnostics["sph0645"].to<JsonObject>();
  detail["state"] = measurement_live ? "ready" :
      (measurement_held ? "held" :
       (stream_live ? "invalid" : "recovering"));
  detail["reason"] = sensor_reason;
  detail["interface_ready"] = health.driver_ready;
  detail["task_running"] = health.task_running;
  detail["stream_active"] = health.stream_active;
  detail["measurement_valid"] = sound.valid;
  if (sound.completed_ms == 0) {
    detail["age_ms"] = nullptr;
  } else {
    detail["age_ms"] = now_ms - sound.completed_ms;
  }
  detail["consecutive_failures"] = health.consecutive_read_errors;
  detail["total_failures"] = health.total_read_errors;
  detail["recovery_count"] = health.recovery_count;
  detail["i2s_bclk_gpio"] = static_cast<int>(zeep::board::kMicBclk);
  detail["i2s_ws_gpio"] = static_cast<int>(zeep::board::kMicWordSelect);
  detail["i2s_data_gpio"] = static_cast<int>(zeep::board::kMicData);
  detail["i2s_slot"] = "left";
  JsonObject inline_diagnostics = sensor["diagnostics"].to<JsonObject>();
  for (JsonPair pair : detail) {
    inline_diagnostics[pair.key()] = pair.value();
  }
}

void addLegacyFields(
    JsonObject document,
    const zeep::EnvironmentSnapshot& environment,
    const zeep::SoundWindow& sound,
    bool sound_live) {
  const bool sht_usable = environmentUsable(environment.sht3x.health);
  const bool opt_usable = environmentUsable(environment.opt3001.health);
  addNumberOrNull(
      document,
      "temperature_c",
      sht_usable ? environment.sht3x.temperature_c : NAN);
  addNumberOrNull(
      document,
      "humidity_rh",
      sht_usable ? environment.sht3x.humidity_rh : NAN);
  addNumberOrNull(
      document,
      "lux",
      opt_usable ? environment.opt3001.lux : NAN);
  addNumberOrNull(document, "sound_dbfs", sound.dbfs);
  addNumberOrNull(document, "sound_laeq_dba", sound.laeq_dba);
  document["sound_valid"] = sound.valid;
  document["sound_weighting"] = "A";
  document["sound_metric"] = "LAeq";
  document["sound_window_ms"] = sound.window_ms;
  if (!sound.valid) {
    document["sound_invalid_reason"] =
        sound.invalid_reason == nullptr ? "unknown" : sound.invalid_reason;
  }
  JsonObject status = document["sensor_status"].to<JsonObject>();
  status["sht3x_dis"] = sht_usable;
  status["opt3001"] = opt_usable;
  status["sph0645"] = sound_live;
}

zeep::SoundWindow currentSoundWindow(
    const zeep::SoundWindow& latest_sound,
    bool has_sound_window,
    uint32_t now_ms,
    const zeep::AudioHealth& audio_health,
    float calibration_offset_db) {
  if (has_sound_window &&
      now_ms - latest_sound.completed_ms <= kSoundWindowFreshMs) {
    // A completed 10-second window remains current for 15 seconds. Reusing it
    // once around a scheduler boundary avoids a false invalid pulse when the
    // audio task completes a few milliseconds after the telemetry deadline.
    return latest_sound;
  }

  zeep::SoundWindow unavailable;
  unavailable.ready = true;
  unavailable.window_ms = zeep::board::kPublishPeriodMs;
  unavailable.wall_window_ms = zeep::board::kPublishPeriodMs;
  unavailable.calibration_offset_db = calibration_offset_db;
  if (!audio_health.driver_ready) {
    unavailable.invalid_reason = "i2s_driver_unavailable";
  } else if (!audio_health.task_running) {
    unavailable.invalid_reason = "audio_task_unavailable";
  } else if (!audio_health.stream_active) {
    unavailable.invalid_reason = "i2s_no_data";
  } else {
    unavailable.invalid_reason = "sound_window_pending";
  }
  return unavailable;
}

}  // namespace

namespace zeep {

TelemetryPublisher::TelemetryPublisher(
    AudioMeter& audio_meter,
    EnvironmentSensors& environment_sensors)
    : audio_meter_(audio_meter),
      environment_sensors_(environment_sensors) {}

void TelemetryPublisher::begin(uint32_t boot_id) {
  boot_id_ = boot_id;
}

void TelemetryPublisher::recordSoundWindow(const SoundWindow& sound) {
  latest_sound_ = sound;
  has_sound_window_ = true;
}

void TelemetryPublisher::publishTelemetry(uint32_t now_ms) {
  const EnvironmentSnapshot environment =
      environment_sensors_.snapshot(now_ms);
  const AudioHealth audio_health = audio_meter_.health(now_ms);
  const SoundWindow sound = currentSoundWindow(
      latest_sound_,
      has_sound_window_,
      now_ms,
      audio_health,
      audio_meter_.calibrationOffset());

  JsonDocument document;
  document["schema"] = kTelemetrySchema;
  document["version"] = kTelemetryVersion;
  document["schema_version"] = 1;
  document["event"] = "environment";
  document["source"] = "sensorhub1_firmware";
  document["hub_id"] = "sensorhub1";
  document["firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["sound_firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["boot_id"] = boot_id_;
  document["sequence"] = ++telemetry_sequence_;
  document["monotonic_ms"] = now_ms;
  document["publish_period_ms"] = board::kPublishPeriodMs;

  JsonObject sensors = document["sensors"].to<JsonObject>();
  JsonObject diagnostics =
      document["sensor_diagnostics"].to<JsonObject>();
  addSht3xTelemetry(sensors, diagnostics, environment.sht3x);
  addOpt3001Telemetry(sensors, diagnostics, environment.opt3001);
  addSoundTelemetry(sensors, diagnostics, sound, audio_health, now_ms);

  const bool sht_ready = environmentUsable(environment.sht3x.health) &&
      environment.sht3x.health.last_attempt_ok;
  const bool opt_ready = environmentUsable(environment.opt3001.health) &&
      environment.opt3001.health.last_attempt_ok;
  const bool sound_ready = sound.valid && audio_health.driver_ready &&
      audio_health.task_running && audio_health.stream_active;
  const int ready_count = (sht_ready ? 1 : 0) + (opt_ready ? 1 : 0) +
      (sound_ready ? 1 : 0);
  const int usable_count =
      (environmentUsable(environment.sht3x.health) ? 1 : 0) +
      (environmentUsable(environment.opt3001.health) ? 1 : 0) +
      (sound.valid ? 1 : 0);
  const char* hub_status = ready_count == 3 ? "live" :
      (usable_count > 0 ? "degraded" : "fault");
  document["hub_status"] = hub_status;
  JsonObject hub_diagnostics = document["diagnostics"].to<JsonObject>();
  hub_diagnostics["hub_status"] = hub_status;
  hub_diagnostics["boot_id"] = boot_id_;
  hub_diagnostics["publish_period_ms"] = board::kPublishPeriodMs;
  hub_diagnostics["i2c_bus_ready"] = environment.i2c_bus_ready;
  hub_diagnostics["i2c_recovery_count"] = environment.i2c_recovery_count;
  addLegacyFields(
      document.as<JsonObject>(), environment, sound, sound_ready);

  serializeJson(document, Serial);
  Serial.println();
}

void TelemetryPublisher::publishBootStatus(const char* event) {
  const uint32_t now_ms = millis();
  const EnvironmentSnapshot environment =
      environment_sensors_.snapshot(now_ms);
  const AudioHealth audio_health = audio_meter_.health(now_ms);

  JsonDocument document;
  document["event"] = event;
  document["source"] = "sensorhub1_firmware";
  document["hub_id"] = "sensorhub1";
  document["firmware_version"] = ZEEP_FIRMWARE_VERSION;
  document["boot_id"] = boot_id_;
  document["chip_model"] = ESP.getChipModel();
  document["flash_bytes"] = ESP.getFlashChipSize();
  document["psram_bytes"] = ESP.getPsramSize();
  document["publish_period_ms"] = board::kPublishPeriodMs;
  document["sound_calibration_offset_db"] =
      audio_meter_.calibrationOffset();

  JsonObject inventory = document["inventory"].to<JsonObject>();
  JsonObject sht = inventory["sht3x_dis"].to<JsonObject>();
  sht["address"] = "0x45";
  sht["present"] = environment.sht3x.health.present;
  sht["reason"] = environment.sht3x.health.reason;
  JsonObject opt = inventory["opt3001"].to<JsonObject>();
  opt["address"] = "0x44";
  opt["present"] = environment.opt3001.health.present;
  opt["reason"] = environment.opt3001.health.reason;
  JsonObject mic = inventory["sph0645"].to<JsonObject>();
  mic["interface_ready"] = audio_health.driver_ready;
  mic["task_running"] = audio_health.task_running;
  mic["reason"] = audio_health.reason;

  serializeJson(document, Serial);
  Serial.println();
}

bool TelemetryPublisher::parseFiniteFloat(
    const String& token,
    float* output) {
  if (output == nullptr || token.isEmpty()) {
    return false;
  }
  const char* start = token.c_str();
  char* end = nullptr;
  errno = 0;
  const float value = strtof(start, &end);
  while (end != nullptr && *end == ' ') {
    ++end;
  }
  if (errno != 0 || end == start || end == nullptr || *end != '\0' ||
      !isfinite(value)) {
    return false;
  }
  *output = value;
  return true;
}

void TelemetryPublisher::publishCalibrationResponse(bool accepted) {
  JsonDocument response;
  response["event"] = "calibration_response";
  response["source"] = "sensorhub1_firmware";
  response["hub_id"] = "sensorhub1";
  response["accepted"] = accepted;
  response["sound_calibration_offset_db"] =
      audio_meter_.calibrationOffset();
  serializeJson(response, Serial);
  Serial.println();
}

void TelemetryPublisher::handleCommand(String command) {
  command.trim();
  if (command == "INFO") {
    publishBootStatus("info");
    return;
  }
  if (command == "CAL SOUND RESET") {
    publishCalibrationResponse(audio_meter_.setCalibrationOffset(0.0F));
    return;
  }

  constexpr const char* kPrefix = "CAL SOUND OFFSET ";
  if (command.startsWith(kPrefix)) {
    float value = NAN;
    const String token = command.substring(strlen(kPrefix));
    const bool parsed = parseFiniteFloat(token, &value);
    publishCalibrationResponse(
        parsed && audio_meter_.setCalibrationOffset(value));
  }
}

void TelemetryPublisher::publishInitialTelemetry() {
  publishTelemetry(millis());
  last_publish_ms_ = millis();
}

void TelemetryPublisher::publishIfDue(uint32_t now_ms) {
  if (!deadlineElapsed(
          now_ms,
          last_publish_ms_,
          board::kPublishPeriodMs)) {
    return;
  }
  do {
    last_publish_ms_ += board::kPublishPeriodMs;
  } while (deadlineElapsed(
      now_ms,
      last_publish_ms_,
      board::kPublishPeriodMs));
  publishTelemetry(now_ms);
}

}  // namespace zeep
