#include "audio_meter.h"

#include <Preferences.h>

#include <algorithm>
#include <climits>
#include <cmath>

#include "board_config.h"

namespace zeep {

namespace {

constexpr uint32_t kSampleRateHz = 32000;
constexpr uint32_t kMeterWindowSamples = kSampleRateHz;
constexpr uint32_t kAcousticWindowSamples = kSampleRateHz * 10;
constexpr size_t kReadSamples = 1024;
constexpr size_t kBytesPerSample = sizeof(int32_t);
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
// A healthy Production capture changes on about 97% of adjacent samples.
// A permissive 99.5% threshold let broken DMA buffers appear as real sound.
constexpr float kMaxRepeatedRatio = 0.20F;
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

// A-weighting at 32 kHz. Coefficients are generated from the IEC analogue
// pole/zero definition with a bilinear transform and normalized at 1 kHz.
// The host regression test independently verifies the frequency response.
Biquad a_weighting_1({
    0.3430690102281953,
    -0.6861380204563906,
    0.3430690102281953,
    -1.9919271185967897,
    0.9919434114503273,
});
Biquad a_weighting_2({
    1.0,
    -2.0,
    1.0,
    -1.843990656105489,
    0.8468163240645945,
});
Biquad a_weighting_3({
    1.0,
    2.0,
    1.0,
    0.1794717314686119,
    0.008052525599085385,
});

double dc_previous_input = 0.0;
double dc_previous_output = 0.0;
double sum_square_unweighted = 0.0;
double sum_square_a_weighted = 0.0;
double sum_square_right24 = 0.0;
double sum_square_high16 = 0.0;
double sum_square_low16 = 0.0;
float peak_normalized = 0.0F;
uint32_t accumulated_samples = 0;
uint32_t clipped_samples = 0;
uint32_t zero_samples = 0;
uint32_t repeated_samples = 0;
uint32_t alignment_errors = 0;
uint32_t read_errors = 0;
uint32_t raw_changes = 0;
uint32_t raw_low_byte_nonzero = 0;
uint32_t window_started_ms = 0;
int32_t previous_sample_18 = 0;
int32_t previous_raw_sample = 0;
int32_t raw_min = INT32_MAX;
int32_t raw_max = INT32_MIN;
bool has_previous_sample = false;

int32_t signExtend24(uint32_t value) {
  value &= 0x00FFFFFFU;
  if ((value & 0x00800000U) != 0U) {
    value |= 0xFF000000U;
  }
  return static_cast<int32_t>(value);
}

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

  i2s_chan_config_t channel_config =
      I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  channel_config.dma_desc_num = 8;
  channel_config.dma_frame_num = 512;
  if (i2s_new_channel(&channel_config, nullptr, &rx_channel_) != ESP_OK) {
    return false;
  }

  i2s_std_config_t stream_config = {};
  stream_config.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(kSampleRateHz);
  stream_config.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
      I2S_DATA_BIT_WIDTH_32BIT,
      I2S_SLOT_MODE_MONO);
  stream_config.slot_cfg.slot_mask = I2S_STD_SLOT_LEFT;
  stream_config.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  stream_config.gpio_cfg.bclk = board::kMicBclk;
  stream_config.gpio_cfg.ws = board::kMicWordSelect;
  stream_config.gpio_cfg.dout = I2S_GPIO_UNUSED;
  stream_config.gpio_cfg.din = board::kMicData;
  stream_config.gpio_cfg.invert_flags.mclk_inv = false;
  stream_config.gpio_cfg.invert_flags.bclk_inv = false;
  stream_config.gpio_cfg.invert_flags.ws_inv = false;
  if (i2s_channel_init_std_mode(rx_channel_, &stream_config) != ESP_OK) {
    i2s_del_channel(rx_channel_);
    rx_channel_ = nullptr;
    return false;
  }
  if (i2s_channel_enable(rx_channel_) != ESP_OK) {
    i2s_del_channel(rx_channel_);
    rx_channel_ = nullptr;
    return false;
  }
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
    i2s_channel_disable(rx_channel_);
    i2s_del_channel(rx_channel_);
    rx_channel_ = nullptr;
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
    const esp_err_t result = i2s_channel_read(
        rx_channel_,
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

    const size_t sample_count = bytes_read / kBytesPerSample;
    for (size_t index = 0; index < sample_count; ++index) {
      if (accumulated_samples == 0) {
        window_started_ms = millis();
      }
      // SPH0645 puts its signed 24-bit transport word in bits 31..8 of the
      // 32-bit Philips slot. Preserve all transport bits for quiet signals.
      const int32_t raw_sample = samples[index];
      const uint32_t packed = static_cast<uint32_t>(raw_sample >> 8);
      const int32_t sample_24 = signExtend24(packed);
      const int32_t right24 = sample_24;
      const int16_t high16 = static_cast<int16_t>(
          static_cast<uint32_t>(packed) >> 8);
      const int16_t low16 = static_cast<int16_t>(
          static_cast<uint32_t>(packed) & 0xFFFFU);
      const double normalized_right24 =
          static_cast<double>(right24) / kFullScale24;
      const double normalized_high16 =
          static_cast<double>(high16) / INT16_MAX;
      const double normalized_low16 =
          static_cast<double>(low16) / INT16_MAX;
      sum_square_right24 += normalized_right24 * normalized_right24;
      sum_square_high16 += normalized_high16 * normalized_high16;
      sum_square_low16 += normalized_low16 * normalized_low16;
      raw_min = std::min(raw_min, sample_24);
      raw_max = std::max(raw_max, sample_24);
      if ((packed & 0xFFU) != 0U) {
        ++raw_low_byte_nonzero;
      }
      if (has_previous_sample && sample_24 != previous_raw_sample) {
        ++raw_changes;
      }
      previous_raw_sample = sample_24;
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
  window.debug_dbfs_right24 = dbfsFromRms(std::sqrt(
      sum_square_right24 / accumulated_samples));
  window.debug_dbfs_high16 = dbfsFromRms(std::sqrt(
      sum_square_high16 / accumulated_samples));
  window.debug_dbfs_low16 = dbfsFromRms(std::sqrt(
      sum_square_low16 / accumulated_samples));
  window.raw_min = raw_min;
  window.raw_max = raw_max;
  window.raw_changes = raw_changes;
  window.raw_low_byte_nonzero = raw_low_byte_nonzero;
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
  sum_square_right24 = 0.0;
  sum_square_high16 = 0.0;
  sum_square_low16 = 0.0;
  peak_normalized = 0.0F;
  accumulated_samples = 0;
  clipped_samples = 0;
  zero_samples = 0;
  repeated_samples = 0;
  alignment_errors = 0;
  read_errors = 0;
  raw_changes = 0;
  raw_low_byte_nonzero = 0;
  raw_min = INT32_MAX;
  raw_max = INT32_MIN;
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
  previous_raw_sample = 0;
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
  i2s_channel_disable(rx_channel_);
  delay(kRecoveryPauseMs);
  const bool recovered = i2s_channel_enable(rx_channel_) == ESP_OK;
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
