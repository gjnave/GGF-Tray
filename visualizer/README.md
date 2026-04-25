# Audio Visualizer System Tray

A Windows system tray application that captures system audio and displays a real-time spark particle visualizer in a small window above your taskbar.

## Features

- **System Audio Capture**: Uses Windows WASAPI loopback to capture all system audio
- **Real-time Visualization**: Particle effects respond to bass, mid, and treble frequencies
- **System Tray Integration**: Runs silently in the background with easy access
- **Customizable Settings**: Adjust particle density, speed, bass sensitivity, color cycling, and bass explosion effects
- **Persistent Configuration**: Settings are saved and restored between sessions
- **Frameless Window**: Clean visualization window that stays on top

## Requirements

- Windows 10 or higher
- Python 3.8 or higher

## Installation

1. **Extract all files** to a folder (e.g., `C:\AudioVisualizer\`)

2. **Run install.bat** (right-click and "Run as administrator" if needed)
   - This will create a virtual environment
   - Install all required Python packages
   - Optionally create a startup shortcut

3. **Done!** The installer will guide you through the process.

## Usage

### Starting the Visualizer

1. Double-click `run_visualizer.bat`
2. A cyan circular icon will appear in your system tray
3. The application runs silently in the background

### Activating the Visualizer

1. Right-click the system tray icon
2. Select **"Activate Visualizer"**
3. A small window will appear above your taskbar showing the particle effects
4. Click "Activate Visualizer" again to hide it

### Adjusting Settings

1. Right-click the system tray icon
2. Select **"Settings"**
3. Adjust the following parameters:
   - **Particle Density** (1-20): Number of particles emitted
   - **Speed** (0.1-5.0): Overall animation speed
   - **Bass Sensitivity** (0-5.0): How much bass affects the particles
   - **Color Cycle Speed** (0-100): Rate of automatic color changes
   - **Bass Explosion** (0-5.0): Strength of bass-triggered explosions
4. Click **"Save Settings"** to apply and save

### Exiting the Application

1. Right-click the system tray icon
2. Select **"Quit"**

## Files

- `audio_visualizer_tray.py` - Main Python application
- `requirements.txt` - Python package dependencies
- `install.bat` - Installation script
- `run_visualizer.bat` - Launcher script
- `visualizer_config.json` - Saved settings (created on first save)
- `sparks2.html` - Original visualizer reference (not required to run)

## Configuration File

Settings are stored in `visualizer_config.json`:

```json
{
  "density": 5,
  "speed": 1.0,
  "bassSensitivity": 1.5,
  "colorCycleSpeed": 10,
  "bassExplosion": 1.0
}
```

You can manually edit this file if needed.

## Troubleshooting

### "Python is not installed" error
- Install Python from python.org
- Make sure to check "Add Python to PATH" during installation

### No audio response
- Make sure audio is playing on your system
- Check Windows audio output settings
- Try restarting the application

### Visualizer window doesn't appear
- Check if it's hidden behind other windows
- Try clicking "Activate Visualizer" again
- Restart the application

### Missing packages error
- Run `install.bat` again
- Manually run: `pip install -r requirements.txt --break-system-packages`

### Application won't start
- Check that all files are in the same folder
- Make sure Python 3.8+ is installed
- Check Windows Event Viewer for error details

## Performance Tips

- Lower **Particle Density** for better performance on slower systems
- Reduce **Color Cycle Speed** if you prefer static colors
- Adjust **Bass Sensitivity** based on your audio type (music vs. speech)

## Technical Details

### Audio Capture
- Uses **PyAudioWPatch** for Windows WASAPI loopback
- Captures default audio output device
- Real-time FFT analysis for frequency bands:
  - Bass: 0-10 bins
  - Mid: 10-60 bins
  - Treble: 60-120 bins

### Visualization
- Built with **PyQt6** and **QtWebEngine**
- HTML5 Canvas for rendering
- ~30 FPS update rate
- Particle physics with gravity and decay

### Window Behavior
- Frameless, always-on-top window
- Positioned above system tray automatically
- 400x300 pixels default size
- Transparent background support

## Customization

To modify the visualizer appearance, edit the HTML template in `audio_visualizer_tray.py`:
- Locate the `get_visualizer_html()` method
- Adjust colors, particle sizes, or physics parameters
- Save and restart the application

## Credits

Based on the original Spark Visualizer HTML5 canvas implementation.
Enhanced with system audio capture and system tray integration.

## License

Free to use and modify for personal projects.
