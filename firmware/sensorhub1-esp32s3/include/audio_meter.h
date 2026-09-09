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
  uint32_t repeated_samples = 0;
  uint32_t completed_ms = 0;
  uint32_t sequence = 0;
  const char* invalid_reason = nullptr;
};

struct AudioHealth {
  bool driver_ready = false;
  bool task_running = false;
  bool stream_active = false;
  bool measurement_valid = false;
  uint32_t last_dma_ms = 0;
  uint32_t last_window_ms = 0;
  uint32_t consecutive_read_errors = 0;
  uint32_t total_read_errors = 0;
  uint32_t recovery_count = 0;
  const char* reason = "not_started";
};

class AudioMeter {
 public:
  bool begin();
  bool takeWindow(SoundWindow* output);
  bool setCalibrationOffset(float offset_db);
  float calibrationOffset() const;
  AudioHealth health(uint32_t now_ms) const;

 private:
  static void taskEntry(void* context);
  void readTask();
  void publishAccumulator();
  void resetWindowAccumulator();
  void resetSignalState();
  void recoverStream();

  TaskHandle_t task_handle_ = nullptr;
  mutable portMUX_TYPE result_lock_ = portMUX_INITIALIZER_UNLOCKED;
  SoundWindow pending_;
  float calibration_offset_db_ = 0.0F;
  bool driver_ready_ = false;
  bool task_running_ = false;
  bool last_measurement_valid_ = false;
  uint32_t last_dma_ms_ = 0;
  uint32_t last_window_ms_ = 0;
  uint32_t window_sequence_ = 0;
  uint32_t consecutive_read_errors_ = 0;
  uint32_t total_read_errors_ = 0;
  uint32_t recovery_count_ = 0;
};

}  // namespace zeep
