#pragma once

#include <Arduino.h>
#include <driver/i2s.h>

namespace zeep {

struct SoundWindow {
  bool ready = false;
  bool valid = false;
  float laeq_dba = NAN;
  float dbfs = NAN;
  float a_weighted_dbfs = NAN;
  float rms = NAN;
  float peak = NAN;
  float calibration_offset_db = 0.0F;
  uint32_t window_ms = 0;
  uint32_t wall_window_ms = 0;
  uint32_t sample_count = 0;
  uint32_t clipped_samples = 0;
  uint32_t zero_samples = 0;
  uint32_t read_errors = 0;
  const char* invalid_reason = nullptr;
};

class AudioMeter {
 public:
  bool begin();
  bool takeWindow(SoundWindow* output);
  bool setCalibrationOffset(float offset_db);
  float calibrationOffset() const;
  bool healthy() const;

 private:
  static void taskEntry(void* context);
  void readTask();
  void publishAccumulator();

  TaskHandle_t task_handle_ = nullptr;
  mutable portMUX_TYPE result_lock_ = portMUX_INITIALIZER_UNLOCKED;
  SoundWindow pending_;
  float calibration_offset_db_ = 0.0F;
  bool healthy_ = false;
};

}  // namespace zeep
