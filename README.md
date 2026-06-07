# FLINT

FLINT is a personal AI assistant running on Windows, powered by the Gemini Live API with real-time voice interaction and a wide set of built-in actions.

## Features 

- **Live voice conversation**: real-time audio in/out via Gemini Live
- **Tool-calling**: open apps, search the web, control your browser, manage files, send messages, set reminders, control your computer, and more
- **Screen & camera vision**: FLINT can see your screen or webcam on demand
- **Memory**: remembers things you tell it across sessions
- **Agent tasks**: multi-step autonomous task execution
- **Game management**: Steam & Epic Games integration
- **File processing**: images, PDFs, audio, video, code, spreadsheets, and more

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Rishi0773/FLINT.git
cd FLINT
```

### 2. Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python setup.py
```

### 4. Configure API keys

Copy the example config and fill in your keys:

```bash
copy config\api_keys.example.json config\api_keys.json
```

Then edit `config/api_keys.json`:

```json
{
    "gemini_api_key": "YOUR_GEMINI_API_KEY",
    "openrouter_api_key": "YOUR_OPENROUTER_API_KEY",
    "os_system": "windows"
}
```

- **Gemini API key**: get one at [aistudio.google.com](https://aistudio.google.com)
- **OpenRouter API key**: get one at [openrouter.ai](https://openrouter.ai) (used for agent tasks)

### 5. Run

```bash
python main.py
```

## Requirements

- Python 3.10+
- Windows 10/11
- A working microphone and speakers

## Notes

- `config/api_keys.json` is gitignored: never commit your real keys
- `core/prompt.txt` contains FLINT's personality: feel free to customise it
