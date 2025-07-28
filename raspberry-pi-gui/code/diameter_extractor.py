import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


class DiameterExtractor:
    """Extracts diameter and related metrics from force-deflection data."""

    def __init__(self):
        """Initializes the DiameterExtractor.
        """
        self.zero_offset_mm = 0.0  # Zero offset from calibration
        self.calibration_scaling = -1.5e-02  # Default scaling factor
        self.is_calibrated = False

    def set_calibration(self, known_diameter_mm, measured_flush_idx):
        """Set calibration parameters based on a known reference object.
        
        Args:
            known_diameter_mm (float): Known diameter of reference object
            measured_flush_idx (float): Measured flush index for reference object
        """
        # Calculate what the zero offset should be to make this measurement correct
        # known_diameter = measured_flush_idx * scaling + zero_offset
        # zero_offset = known_diameter - measured_flush_idx * scaling
        self.zero_offset_mm = known_diameter_mm - (measured_flush_idx * self.calibration_scaling)
        self.is_calibrated = True

    def set_zero_offset(self, zero_offset_mm):
        """Set the zero offset from calibration.
        
        Args:
            zero_offset_mm (float): Zero offset in mm from calibration
        """
        self.zero_offset_mm = zero_offset_mm
        self.is_calibrated = True

    def validate_force_data(self, force_data):
        """Validate force-deflection data for measurement quality.
        
        Args:
            force_data (pd.DataFrame): DataFrame containing force sweep measurements
            
        Returns:
            tuple: (is_valid, validation_flags, validation_info)
        """
        validation_flags = []
        validation_info = {}
        
        if force_data is None or force_data.empty:
            validation_flags.append('NO_DATA')
            validation_info['NO_DATA'] = 'No force data available'
            return False, validation_flags, validation_info
        
        # Check for minimum data points
        if len(force_data) < 10:
            validation_flags.append('INSUFFICIENT_DATA')
            validation_info['INSUFFICIENT_DATA'] = f'Only {len(force_data)} data points'
            return False, validation_flags, validation_info
        
        # Check for valid force range
        force_values = force_data['force_N'].values
        if np.all(force_values < 0):
            validation_flags.append('INVALID_FORCE')
            validation_info['INVALID_FORCE'] = 'All force values are negative (sensor error)'
            return False, validation_flags, validation_info
        
        # Check for constant force (stuck sensor)
        force_std = np.std(force_values)
        if force_std < 0.01:  # Very low variation
            validation_flags.append('STUCK_SENSOR')
            validation_info['STUCK_SENSOR'] = f'Force variation too low: {force_std:.4f}'
        
        # Check for reasonable force range
        max_force = np.max(force_values)
        if max_force > 20:  # Unreasonably high force
            validation_flags.append('EXCESSIVE_FORCE')
            validation_info['EXCESSIVE_FORCE'] = f'Maximum force: {max_force:.2f}N'
        
        # Check for missing columns
        required_columns = ['force_N', 'deflection_mm']
        missing_cols = [col for col in required_columns if col not in force_data.columns]
        if missing_cols:
            validation_flags.append('MISSING_COLUMNS')
            validation_info['MISSING_COLUMNS'] = f'Missing: {missing_cols}'
            return False, validation_flags, validation_info
        
        # Data seems valid if we get here
        is_valid = len(validation_flags) == 0
        return is_valid, validation_flags, validation_info

    def get_step_flush_indices(
        self, force_data, smoothing_window=31, polyorder=3
    ):
        """
        Calculates step and flush indices from force data.

        Args:
            force_data (pd.DataFrame): DataFrame containing force sweep
            measurements with a 'force_N' column.
            smoothing_window (int): Window length for Savitzky-Golay filter.
            Must be an odd integer.
            polyorder (int): Polynomial order for Savitzky-Golay filter.

        Returns:
            tuple: (step_idx, flush_idx, relative_flush_idx)
        """
        # Validate data first
        is_valid, _, _ = self.validate_force_data(force_data)
        if not is_valid:
            # Return safe default values for invalid data
            return 0, 0, 0
        
        force = force_data['force_N'].to_numpy()
        
        # Ensure smoothing window is appropriate for data size
        data_length = len(force)
        if smoothing_window >= data_length:
            smoothing_window = max(5, data_length // 2)
            if smoothing_window % 2 == 0:  # Must be odd
                smoothing_window -= 1
        
        try:
            smoothed = savgol_filter(force, window_length=smoothing_window, polyorder=polyorder)
            gradient = np.gradient(smoothed)
            step_idx = np.argmax(gradient)
            relative_flush_idx = np.argmin(gradient)
            flush_idx = force_data.index.max() - relative_flush_idx
            return step_idx, flush_idx, relative_flush_idx
        except Exception as e:
            # If smoothing fails, return safe defaults
            print(f"Warning: Error in step/flush index calculation: {e}")
            return 0, len(force) // 2, len(force) // 2

    def diameter_from_force_data(self, force_data):
        """
        Analyze force sweep data to calculate diameter and identify potential
        issues.

        Args:
            force_data (pd.DataFrame): DataFrame containing force sweep
            measurements with 'force_N' and 'deflection_mm' columns.

        Returns:
            tuple: (calculated_diameter, list of flag strings, list of flaginfo
            dictionaries)
        """
        flags = []
        flaginfo = {}

        # Validate data first
        is_valid, validation_flags, validation_info = self.validate_force_data(force_data)
        if not is_valid:
            flags.extend(validation_flags)
            flaginfo.update(validation_info)
            # Return default diameter for invalid data
            return 0.0, flags, [flaginfo]

        # Add validation flags as warnings even if data is valid
        if validation_flags:
            flags.extend(validation_flags)
            flaginfo.update(validation_info)

        # Check 5.5N intersections by finding where force crosses 5.5N threshold
        force_array = force_data['force_N'].values
        intersections = 0
        for i in range(len(force_array) - 1):
            if (
                (force_array[i] <= 5.5 and force_array[i + 1] > 5.5) or
                (force_array[i] >= 5.5 and force_array[i + 1] < 5.5)
            ):
                intersections += 1

        if intersections != 2:
            flags.append('MIP')
            flaginfo['MIP'] = f'MIP:{intersections}'

        # Check stepper drift
        start_pos = force_data['deflection_mm'].iloc[0]
        end_pos = force_data['deflection_mm'].iloc[-1]
        drift = abs(end_pos - start_pos)

        if drift > 0.05:  # 0.025mm threshold
            flags.append('LSD')
            flaginfo['LSD'] = f'LSD:{drift:.3f}mm'
        elif drift > 0.025:
            flags.append('MSD')
            flaginfo['MSD'] = f'MSD:{drift:.3f}mm'

        # Calculate flush index using smoothed data
        # Note: Using default smoothing parameters here
        _, flush_idx, _ = self.get_step_flush_indices(force_data)

        # Convert flush index to diameter
        # The flush_idx represents the position where the force drops off
        # We need to convert this to a physical diameter measurement
        # This should be calibrated using known reference objects
        calculated_diameter = flush_idx * self.calibration_scaling + self.zero_offset_mm

        # Add calibration warning if not calibrated
        if not self.is_calibrated:
            flags.append('NOT_CALIBRATED')
            flaginfo['NOT_CALIBRATED'] = 'Measurement taken without calibration'

        return calculated_diameter, flags, [flaginfo]
