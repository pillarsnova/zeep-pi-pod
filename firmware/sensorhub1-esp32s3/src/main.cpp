#include <Arduino.h>
#include <esp_system.h>

#include "audio_meter.h"
#include "board_config.h"
#include "environment_sensors.h"
#include "telemetry_publisher.h"

namespace {

zeep::AudioMeter audio_meter;
zeep::EnvironmentSensors environment_sensors;
zeep::TelemetryPublisher telemetry(audio_meter, environment_sensors);

void collectAudioWindows() {
  zeep::SoundWindow sound;
  while (audio_meter.takeWindow(&sound)) {
    telemetry.recordSoundWindow(sound);
  }
}

}  // namespace

void setup() {
  Serial.begin(zeep::board::kSerialBaud);
  Serial.setTimeout(50);
  delay(800);

  telemetry.begin(esp_random());
  environment_sensors.begin();
  audio_meter.begin();
  telemetry.publishBootStatus();

  // Publish the first I2C snapshot immediately. SPH0645 remains explicitly
  // invalid until its first complete 10-second LAeq(A) window.
  environment_sensors.poll(millis());
  telemetry.publishInitialTelemetry();
}

void loop() {
  environment_sensors.poll(millis());
  collectAudioWindows();

  if (Serial.available()) {
    telemetry.handleCommand(Serial.readStringUntil('\n'));
  }
  telemetry.publishIfDue(millis());
  delay(5);
}
