# The Nesting Sandbox

A concentric multi-agent reasoning engine that solves problems through layered observation and asymmetric information flow. Built on OpenAI's API.

## How It Works

The system is organized as nested "boxes" — concentric layers of AI agents where inner boxes are focused and blind to outer boxes, while outer boxes are omniscient observers that selectively pull what's relevant.

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┐
│  Boxes 3+  (Specialists)          │
│  Full read access, selective pull  │
│   ┌───────────────────────────┐   │
│   │  Box 2  (Extrapolator)    │   │
│   │  Watches Box 1, extends   │   │
│   │   ┌───────────────────┐   │   │
│   │   │  Box 1  (Solver)  │   │   │
│   │   │  Core problem     │   │   │
│   │   └───────────────────┘   │   │
│   └───────────────────────────┘   │
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
```

## Three Modes

| Mode | Box 1 | Box 2 | Purpose |
|------|-------|-------|---------|
| **Solve** | Solver | Extrapolator | Find the answer |
| **Explore** | Explorer | Cartographer | Learn from trying |
| **Freeform** | Analyst | Meta-Analyst | See what happens |

### Solve Mode
Standard problem-solving. Box 1 grinds on the question, Box 2 extrapolates every finding to its logical conclusion. Event types: hypothesis, evidence, conclusion, dead_end, connection, question.

### Explore Mode
For "impossible" problems where the journey IS the output. Box 1 explores the problem space exhaustively, lingering on failures to extract data from them. Box 2 acts as a cartographer, mapping the terrain of what's possible vs impossible. Event types: discovery, constraint, approach, failure_analysis, partial_solution, assumption, unexpected, boundary, pattern, frontier.

### Freeform Mode
The system decides its own approach. Boxes adapt in real-time — if the problem looks solvable, they solve it; if not, they explore. All event types are available.

## Model Tiering

| Role | Model | $/1M in | $/1M out | Why |
|------|-------|---------|----------|-----|
| Box 1 | o4-mini | $1.10 | $4.40 | Built-in chain-of-thought reasoning |
| Box 2 | gpt-4.1 | $2.00 | $8.00 | 1M token context, best instruction-following |
| Specialists | gpt-4.1-mini | $0.40 | $1.60 | 1M context at 5x cheaper |
| Relevance Gate | gpt-4.1-nano | $0.10 | $0.40 | Binary yes/no pre-filter |

## Cost Controls

- **Pre-run estimate**: Nano model scores complexity, projects cost range
- **Live tracker**: Real-time $/minute burn rate, per-box breakdown
- **Budget cap**: At 80% → boxes enter "conclude" mode. At 95% → hard stop
- **Post-run receipt**: Full token and cost breakdown per box

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Run
uvicorn app.main:app --reload
# Open http://localhost:8000
```

You can also provide an API key per-run in the UI header.

## Android App

An Android wrapper app is included under `android-app/`. It loads the Nesting Sandbox web UI in a `WebView`.

### Build and run

```bash
cd android-app
./gradlew assembleDebug
```

Then install `app/build/outputs/apk/debug/app-debug.apk` on a device/emulator.

By default, the app points to `http://10.0.2.2:8000` (Android emulator loopback to your host machine).

To change the endpoint, edit this line in `android-app/app/build.gradle.kts`:

```kotlin
buildConfigField("String", "NESTING_SANDBOX_BASE_URL", "\"http://10.0.2.2:8000\"")
```

### Create and push a dedicated Git repo for the Android app

Use the helper script to create a clean standalone repo from `android-app/`:

```bash
# Create local standalone repo at ../Nesting-Sandbox-Android
./android-app/create-standalone-repo.sh

# Or create + push directly
./android-app/create-standalone-repo.sh ../Nesting-Sandbox-Android git@github.com:<you>/nesting-sandbox-android.git
```
