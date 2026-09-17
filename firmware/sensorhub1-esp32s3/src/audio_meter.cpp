#include "audio_meter.h"

#include <Preferences.h>

#include <algorithm>
#include <cmath>

#include <soc/i2s_struct.h>

#include "board_config.h"

namespace zeep {

namespace {

constexpr uint32_t kSampleRateHz = 48000;
constexpr uint32_t kMeterWindowSamples = kSampleRateHz;
constexpr uint32_t kAcousticWindowSamples = kSampleRateHz * 10;
constexpr size_t kReadSamples = 1024;
// The ESP32-S3 legacy I2S driver exposes the microphone's complete signed
// 24-bit word MSB-aligned in its 32-bit DMA slot. The SPH0645 has 18-bit
// acoustic precision, but discarding another six bits here destroys quiet
// signal resolution on the Production board. Preserve the transport word and
// normalize against signed 24-bit full scale.
constexpr uint8_t kPcmTransportPaddingBits = 8;
constexpr float kFullScale24 = 8388607.0F;
constexpr float kReferenceSplDb = 94.0F;
constexpr float kSensitivityDbfs = -26.0F;
// SPH0645LM4H-B sensitivity is already specified in dBFS at 94 dB SPL.
// Therefore the datasheet conversion offset is 94 - (-26) = 120 dB.
// Do not add a separate sine peak-to-RMS correction here.
constexpr float kDatasheetOffsetDb = kReferenceSplDb - kSensitivityDbfs;
constexpr float kClipThreshold = 0.98F;
constexpr float kMaxClipRatio = 0.001F;
constexpr float kMaxZeroRatio = 0.95F;
constexpr float kMaxRepeatedRatio = 0.995F;
constexpr uint32_t kStreamStaleMs = 1500;
constexpr uint32_t kReadErrorsBeforeRecovery = 20;
constexpr uint32_t kRecoveryPauseMs = 50;

Preferences preferences;

struct BiquadCoefficients {
  double b0;
  double b1;
  double b2;
  double a1;
  double a2;
};

class Biquad {
 public:
  explicit Biquad(BiquadCoefficients coefficients)
      : coefficients_(coefficients) {}

  double process(double input) {
    const double output = coefficients_.b0 * input + delay_1_;
    delay_1_ = coefficients_.b1 * input -
               coefficients_.a1 * output + delay_2_;
    delay_2_ = coefficients_.b2 * input -
               coefficients_.a2 * output;
    return output;
  }

  void reset() {
    delay_1_ = 0.0;
    delay_2_ = 0.0;
  }

 private:
  BiquadCoefficients coefficients_;
  double delay_1_ = 0.0;
  double delay_2_ = 0.0;
};

// A-weighting at 48 kHz. Coefficients are generated from the IEC analogue
// pole/zero definition with a bilinear transform and normalized at 1 kHz.
// The host regression test independently verifies the frequency response.
Biquad a_weighting_1({
    0.23418304260355596,
    -0.46836608520711193,
    0.23418304260355596,
    -1.9946144559930215,
    0.99462170701408426,
});
Biquad a_weighting_2({
    1.0,
    -2.0,
    1.0,
    -1.8938704947230707,
    0.89515976909466166,
});
Biquad a_weighting_3({
    1.0,
    2.0,
    1.0,
    -0.22455845805977914,
    0.012606625271546396,
});

double dc_previous_input = 0.0;
double dc_previous_output = 0.0;
double sum_square_unweighted = 0.0;
double sum_square_a_weighted = 0.0;
float peak_normalized = 0.0F;
uint32_t accumulated_samples = 0;
uint32_t clipped_samples = 0;
uint32_t zero_samples = 0;
uint32_t repeated_samples = 0;
uint32_t alignment_errors = 0;
uint32_t read_errors = 0;
uint32_t window_started_ms = 0;
int32_t previous_sample_18 = 0;
bool has_previous_sample = false;

double dcBlock(double input) {
  constexpr double kPole = 0.9992;
  const double output = input - dc_previous_input +
                        kPole * dc_previous_output;
  dc_previous_input = input;
  dc_previous_output = output;
  return output;
}

float dbfsFromRms(double rms) {
  if (!std::isfinite(rms) || rms <= 0.0) {
    return NAN;
  }
  return static_cast<float>(20.0 * std::log10(rms));
}

}  // namespace

bool AudioMeter::begin() {
  preferences.begin("zeep-sound", false);
  calibration_offset_db_ = preferences.getFloat("offset-db", 0.0F);
  calibration_valid_ = preferences.getBool("calibrated", false);
  if (!isfinite(calibration_offset_db_) ||
      calibration_offset_db_ < -30.0F ||
      calibration_offset_db_ > 30.0F) {
    calibration_offset_db_ = 0.0F;
    calibration_valid_ = false;
  }

  i2s_config_t i2s_config = {};
  i2s_config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX);
  i2s_config.sample_rate = kSampleRateHz;
  i2s_config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  i2s_config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  i2s_config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  i2s_config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  i2s_config.dma_buf_count = 8;
  i2s_config.dma_buf_len = 512;
  i2s_config.use_apll = true;
  i2s_config.tx_desc_auto_clear = false;
  i2s_config.fixed_mclk = 0;
  if (i2s_driver_install(I2S_NUM_0, &i2s_config, 0, nullptr) != ESP_OK) {
    return false;
  }

  i2s_pin_config_t pin_config = {};
  pin_config.mck_io_num = I2S_PIN_NO_CHANGE;
  pin_config.bck_io_num = board::kMicBclk;
  pin_config.ws_io_num = board::kMicWordSelect;
  pin_config.data_out_num = I2S_PIN_NO_CHANGE;
  pin_config.data_in_num = board::kMicData;
  if (i2s_set_pin(I2S_NUM_0, &pin_config) != ESP_OK) {
    i2s_driver_uninstall(I2S_NUM_0);
    return false;
  }
  // SPH0645 changes SD close to the sampling edge. The classic ESP32 SLM
  // workaround sets RX_SD_IN_DELAY mode 2; ESP32-S3 exposes the equivalent as
  // rx_sd_in_dm. Keep Philips MSB shift enabled and sample SD on the delayed
  // edge to prevent long zero runs and full-scale glitches.
  I2S0.rx_conf1.rx_msb_shift = 1;
  I2S0.rx_timing.rx_sd_in_dm = 2;

  resetWindowAccumulator();
  resetSignalState();
  driver_ready_ = true;
  task_running_ = xTaskCreatePinnedToCore(
      taskEntry,
      "sph0645-laeq",
      12288,
      this,
      4,
      &task_handle_,
      0) == pdPASS;
  if (!task_running_) {
    i2s_driver_uninstall(I2S_NUM_0);
    driver_ready_ = false;
  }
  return task_running_;
}

bool AudioMeter::takeWindow(SoundWindow* output) {
  if (output == nullptr) {
    return false;
  }
  portENTER_CRITICAL(&result_lock_);
  if (!pending_.ready) {
    portEXIT_CRITICAL(&result_lock_);
    return false;
  }
  *output = pending_;
  pending_.ready = false;
  portEXIT_CRITICAL(&result_lock_);
  return true;
}

bool AudioMeter::setCalibrationOffset(float offset_db) {
  if (!isfinite(offset_db) || offset_db < -30.0F || offset_db > 30.0F) {
    return false;
  }
  // Mark the record uncalibrated before changing the value. If power is lost
  // between writes, the next boot will expose the reading as uncalibrated
  // instead of trusting a partially committed pair.
  if (preferences.putBool("calibrated", false) == 0) {
    return false;
  }
  if (preferences.putFloat("offset-db", offset_db) != sizeof(float)) {
    return false;
  }
  if (preferences.putBool("calibrated", true) == 0) {
    return false;
  }
  portENTER_CRITICAL(&result_lock_);
  calibration_offset_db_ = offset_db;
  calibration_valid_ = true;
  portEXIT_CRITICAL(&result_lock_);
  return true;
}

bool AudioMeter::resetCalibration() {
  const bool state_saved = preferences.putBool("calibrated", false) != 0;
  const bool offset_saved = state_saved &&
      preferences.putFloat("offset-db", 0.0F) == sizeof(float);
  if (!offset_saved || !state_saved) {
    return false;
  }
  portENTER_CRITICAL(&result_lock_);
  calibration_offset_db_ = 0.0F;
  calibration_valid_ = false;
  portEXIT_CRITICAL(&result_lock_);
  return true;
}

float AudioMeter::calibrationOffset() const {
  portENTER_CRITICAL(&result_lock_);
  const float value = calibration_offset_db_;
  portEXIT_CRITICAL(&result_lock_);
  return value;
}

bool AudioMeter::isCalibrated() const {
  portENTER_CRITICAL(&result_lock_);
  const bool value = calibration_valid_;
  portEXIT_CRITICAL(&result_lock_);
  return value;
}

AudioHealth AudioMeter::health(uint32_t now_ms) const {
  portENTER_CRITICAL(&result_lock_);
  AudioHealth snapshot;
  snapshot.driver_ready = driver_ready_;
  snapshot.task_running = task_running_;
  snapshot.last_dma_ms = last_dma_ms_;
  snapshot.last_window_ms = last_window_ms_;
  snapshot.measurement_valid = last_measurement_valid_;
  snapshot.consecutive_read_errors = consecutive_read_errors_;
  snapshot.total_read_errors = total_read_errors_;
  snapshot.recovery_count = recovery_count_;
  portEXIT_CRITICAL(&result_lock_);

  snapshot.stream_active = snapshot.last_dma_ms != 0 &&
      now_ms - snapshot.last_dma_ms <= kStreamStaleMs;
  if (!snapshot.driver_ready) {
    snapshot.reason = "i2s_driver_unavailable";
  } else if (!snapshot.task_running) {
    snapshot.reason = "audio_task_unavailable";
  } else if (!snapshot.stream_active) {
    snapshot.reason = "i2s_no_data";
  } else if (!snapshot.measurement_valid) {
    snapshot.reason = "measurement_invalid";
  } else {
    snapshot.reason = "ok";
  }
  return snapshot;
}

void AudioMeter::taskEntry(void* context) {
  static_cast<AudioMeter*>(context)->readTask();
}

void AudioMeter::readTask() {
  int32_t samples[kReadSamples];
  while (true) {
    size_t bytes_read = 0;
    const esp_err_t result = i2s_read(
        I2S_NUM_0,
        samples,
        sizeof(samples),
        &bytes_read,
        pdMS_TO_TICKS(250));
    if (result != ESP_OK || bytes_read == 0) {
      ++read_errors;
      portENTER_CRITICAL(&result_lock_);
      ++consecutive_read_errors_;
      ++total_read_errors_;
      const bool should_recover =
          consecutive_read_errors_ >= kReadErrorsBeforeRecovery;
      portEXIT_CRITICAL(&result_lock_);
      if (should_recover) {
        recoverStream();
      }
      continue;
    }

    portENTER_CRITICAL(&result_lock_);
    last_dma_ms_ = millis();
    consecutive_read_errors_ = 0;
    portEXIT_CRITICAL(&result_lock_);

    const size_t sample_count = bytes_read / sizeof(int32_t);
    for (size_t index = 0; index < sample_count; ++index) {
      if (accumulated_samples == 0) {
        window_started_ms = millis();
      }
      // Philips mode resolves the one-bit I2S delay. Production capture shows
      // that the legacy ESP32-S3 driver returns the complete 24-bit transport
      // word in bits 31..8; the low six acoustic-precision bits must not be
      // treated as DMA padding.
      const int32_t raw_sample = samples[index];
      const int32_t sample_24 = raw_sample >> kPcmTransportPaddingBits;
      const double normalized = static_cast<double>(sample_24) / kFullScale24;
      const double unweighted = dcBlock(normalized);
      acoustic_classifier_.addSample(
          static_cast<float>(normalized),
          static_cast<float>(unweighted));
      double weighted = a_weighting_1.process(unweighted);
      weighted = a_weighting_2.process(weighted);
      weighted = a_weighting_3.process(weighted);

      acoustic_sum_square_ += unweighted * unweighted;
      acoustic_sum_square_a_ += weighted * weighted;
      acoustic_peak_ = std::max(
          acoustic_peak_,
          static_cast<float>(std::abs(normalized)));
      if (++acoustic_samples_ >= kAcousticWindowSamples) {
        publishAcousticAccumulator();
      }

      sum_square_unweighted += unweighted * unweighted;
      sum_square_a_weighted += weighted * weighted;
      peak_normalized = std::max(
          peak_normalized,
          static_cast<float>(std::abs(normalized)));
      if (std::abs(normalized) >= kClipThreshold) {
        ++clipped_samples;
      }
      if (sample_24 == 0) {
        ++zero_samples;
      }
      if (has_previous_sample && sample_24 == previous_sample_18) {
        ++repeated_samples;
      }
      previous_sample_18 = sample_24;
      has_previous_sample = true;
      ++accumulated_samples;

      if (accumulated_samples >= kMeterWindowSamples) {
        publishAccumulator();
      }
    }
  }
}

void AudioMeter::publishAccumulator() {
  SoundWindow window;
  window.ready = true;
  window.sample_count = accumulated_samples;
  window.window_ms = static_cast<uint32_t>(
      1000ULL * accumulated_samples / kSampleRateHz);
  window.wall_window_ms = millis() - window_started_ms;
  window.clipped_samples = clipped_samples;
  window.zero_samples = zero_samples;
  window.read_errors = read_errors;
  window.repeated_samples = repeated_samples;
  window.alignment_errors = alignment_errors;
  window.peak = peak_normalized;
  window.calibration_offset_db = calibrationOffset();
  window.dba_calibrated = isCalibrated();
  window.completed_ms = millis();

  const double rms = std::sqrt(
      sum_square_unweighted / accumulated_samples);
  const double a_weighted_rms = std::sqrt(
      sum_square_a_weighted / accumulated_samples);
  window.rms = static_cast<float>(rms);
  window.dbfs = dbfsFromRms(rms);
  window.a_weighted_dbfs = dbfsFromRms(a_weighted_rms);
  window.laeq_dba = kDatasheetOffsetDb + window.a_weighted_dbfs +
                    window.calibration_offset_db;
  window.acoustic = latest_acoustic_;

  const float clip_ratio = static_cast<float>(clipped_samples) /
                           accumulated_samples;
  const float zero_ratio = static_cast<float>(zero_samples) /
                           accumulated_samples;
  const float repeated_ratio = static_cast<float>(repeated_samples) /
                               accumulated_samples;
  window.clip_ratio = clip_ratio;
  window.zero_ratio = zero_ratio;
  window.repeated_ratio = repeated_ratio;
  if (!isfinite(window.laeq_dba) || !isfinite(window.dbfs)) {
    window.invalid_reason = "non_finite";
  } else if (read_errors > 0) {
    window.invalid_reason = "i2s_read_error";
  } else if (window.wall_window_ms < 900 || window.wall_window_ms > 1100) {
    window.invalid_reason = "sample_clock_mismatch";
  } else if (clip_ratio > kMaxClipRatio) {
    window.invalid_reason = "clipping";
  } else if (zero_ratio > kMaxZeroRatio) {
    window.invalid_reason = "digital_silence";
  } else if (repeated_ratio > kMaxRepeatedRatio) {
    window.invalid_reason = "pcm_stuck";
  } else if (window.peak <= 0.0F || window.peak > 1.0F) {
    window.invalid_reason = "pcm_out_of_range";
  } else if (window.laeq_dba < 30.0F || window.laeq_dba > 130.0F) {
    window.invalid_reason = "outside_cem_range";
  } else {
    window.valid = true;
  }

  portENTER_CRITICAL(&result_lock_);
  window.sequence = ++window_sequence_;
  pending_ = window;
  last_window_ms_ = window.completed_ms;
  last_measurement_valid_ = window.valid;
  portEXIT_CRITICAL(&result_lock_);

  // Keep DC-blocker, A-weighting and DSP history across adjacent one-second
  // meter windows. Resetting filter state creates artificial transients.
  resetWindowAccumulator();
}

void AudioMeter::publishAcousticAccumulator() {
  const double rms = std::sqrt(
      acoustic_sum_square_ / acoustic_samples_);
  const double a_weighted_rms = std::sqrt(
      acoustic_sum_square_a_ / acoustic_samples_);
  const float dbfs_a = dbfsFromRms(a_weighted_rms);
  const float laeq_dba =
      kDatasheetOffsetDb + dbfs_a + calibrationOffset();
  AcousticFeatures features = acoustic_classifier_.finish(
      laeq_dba,
      static_cast<float>(rms),
      acoustic_peak_);
  features.window_ms = 1000ULL * acoustic_samples_ / kSampleRateHz;
  features.completed_ms = millis();
  features.sequence = ++acoustic_sequence_;
  latest_acoustic_ = features;
  resetAcousticAccumulator();
}

void AudioMeter::resetWindowAccumulator() {
  sum_square_unweighted = 0.0;
  sum_square_a_weighted = 0.0;
  peak_normalized = 0.0F;
  accumulated_samples = 0;
  clipped_samples = 0;
  zero_samples = 0;
  repeated_samples = 0;
  alignment_errors = 0;
  read_errors = 0;
  window_started_ms = 0;
}

void AudioMeter::resetAcousticAccumulator() {
  acoustic_samples_ = 0;
  acoustic_sum_square_ = 0.0;
  acoustic_sum_square_a_ = 0.0;
  acoustic_peak_ = 0.0F;
  acoustic_classifier_.reset();
}

void AudioMeter::resetSignalState() {
  previous_sample_18 = 0;
  has_previous_sample = false;
  dc_previous_input = 0.0;
  dc_previous_output = 0.0;
  a_weighting_1.reset();
  a_weighting_2.reset();
  a_weighting_3.reset();
  latest_acoustic_ = AcousticFeatures{};
  resetAcousticAccumulator();
}

void AudioMeter::recoverStream() {
  i2s_stop(I2S_NUM_0);
  delay(kRecoveryPauseMs);
  const bool recovered = i2s_start(I2S_NUM_0) == ESP_OK;
  resetWindowAccumulator();
  resetSignalState();
  portENTER_CRITICAL(&result_lock_);
  ++recovery_count_;
  consecutive_read_errors_ = 0;
  driver_ready_ = recovered;
  last_measurement_valid_ = false;
  portEXIT_CRITICAL(&result_lock_);
}

}  // namespace zeep
