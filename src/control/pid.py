class PIDController:
    """
    PID controller with anti-windup, derivative-on-measurement, and EMA-filtered derivative.

    Supports two modes:
      - "positional": output = absolute voltage (legacy behavior)
      - "incremental": output = accumulated output starting from initial_output,
        with deltas computed from error changes. Provides bumpless transfer.
    """

    def __init__(self, kp=0.0, ki=0.0, kd=0.0, output_min=None, output_max=None,
                 d_filter_coeff=0.1, mode="positional"):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max
        self.d_filter_coeff = d_filter_coeff
        self.mode = mode

        # Positional mode state
        self._integral = 0.0
        self._prev_measurement = None
        self._filtered_derivative = 0.0

        # Incremental mode state
        self._prev_error = None
        self._accumulated_output = 0.0

    def compute(self, setpoint, measurement, dt):
        """
        Compute PID output.

        In positional mode: returns absolute voltage.
        In incremental mode: returns accumulated output (starting from initial_output),
        updated by velocity-form deltas each step.
        """
        if dt <= 0:
            return self._accumulated_output if self.mode == "incremental" else 0.0

        error = setpoint - measurement

        if self.mode == "incremental":
            return self._compute_incremental(error, measurement, dt)
        else:
            return self._compute_positional(error, measurement, dt)

    def _compute_positional(self, error, measurement, dt):
        """Legacy positional PID: output = Kp*e + Ki*integral + Kd*derivative."""
        # --- Proportional ---
        p_term = self.kp * error

        # --- Integral with anti-windup ---
        raw_output = p_term + self.ki * self._integral
        saturated_high = self.output_max is not None and raw_output >= self.output_max
        saturated_low = self.output_min is not None and raw_output <= self.output_min
        if not ((saturated_high and error > 0) or (saturated_low and error < 0)):
            self._integral += error * dt

        i_term = self.ki * self._integral

        # --- Derivative on measurement (avoids derivative kick) ---
        if self._prev_measurement is not None:
            raw_derivative = -(measurement - self._prev_measurement) / dt
            alpha = self.d_filter_coeff
            self._filtered_derivative = (alpha * raw_derivative +
                                         (1.0 - alpha) * self._filtered_derivative)
        self._prev_measurement = measurement

        d_term = self.kd * self._filtered_derivative

        output = p_term + i_term + d_term
        return self._clamp(output)

    def _compute_incremental(self, error, measurement, dt):
        """Velocity-form PID: delta = Kp*(e - e_prev) + Ki*e*dt + Kd*d_term."""
        # --- Derivative on measurement ---
        d_contribution = 0.0
        if self._prev_measurement is not None:
            raw_derivative = -(measurement - self._prev_measurement) / dt
            alpha = self.d_filter_coeff
            self._filtered_derivative = (alpha * raw_derivative +
                                         (1.0 - alpha) * self._filtered_derivative)
            d_contribution = self.kd * self._filtered_derivative
        self._prev_measurement = measurement

        # --- Compute delta ---
        if self._prev_error is None:
            # First call: no previous error, use only integral term
            delta = self.ki * error * dt + d_contribution
        else:
            delta = (self.kp * (error - self._prev_error) +
                     self.ki * error * dt +
                     d_contribution)

        self._prev_error = error

        # --- Anti-windup: don't accumulate if it would push past limits ---
        candidate = self._accumulated_output + delta
        if self.output_max is not None and candidate > self.output_max and delta > 0:
            self._accumulated_output = self.output_max
        elif self.output_min is not None and candidate < self.output_min and delta < 0:
            self._accumulated_output = self.output_min
        else:
            self._accumulated_output = candidate

        return self._clamp(self._accumulated_output)

    def reset(self, initial_output=None):
        """Reset internal state. In incremental mode, initial_output sets the starting point."""
        self._integral = 0.0
        self._prev_measurement = None
        self._filtered_derivative = 0.0
        self._prev_error = None
        if initial_output is not None:
            self._accumulated_output = initial_output
        else:
            self._accumulated_output = 0.0

    def soft_reset(self):
        """Clear derivative state but keep accumulated output (for setpoint changes)."""
        self._prev_measurement = None
        self._filtered_derivative = 0.0
        self._prev_error = None

    def update_gains(self, kp=None, ki=None, kd=None, d_filter_coeff=None):
        """Update gains without resetting state."""
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd
        if d_filter_coeff is not None:
            self.d_filter_coeff = d_filter_coeff

    def _clamp(self, value):
        if self.output_min is not None and value < self.output_min:
            return self.output_min
        if self.output_max is not None and value > self.output_max:
            return self.output_max
        return value
