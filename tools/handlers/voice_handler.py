import asyncio
import importlib
from pathlib import Path


voice_model = None


def feature_enabled(config):
    return bool(config.get("features", {}).get("GALAXY_VOICE_ENABLED", False))


def _max_duration(config):
    return int(config.get("voice", {}).get("max_duration_seconds", 60))


def _load_model(config):
    global voice_model
    if voice_model is not None:
        return voice_model
    try:
        faster_whisper = importlib.import_module("faster_whisper")
        model_name = config.get("voice", {}).get("whisper_model", "base")
        voice_model = faster_whisper.WhisperModel(
            model_name, device="cpu", compute_type="int8"
        )
    except Exception:
        voice_model = "FAILED"
    return voice_model


async def handle_voice(update, context, config, on_text_ready):
    if not feature_enabled(config):
        return False

    voice = update.message.voice
    if not voice:
        return False

    if voice.duration > _max_duration(config):
        await update.message.reply_text("⏳ Voice messages limited to 60 seconds")
        return True

    model = _load_model(config)
    if model == "FAILED":
        await update.message.reply_text(
            "⚠️ Voice transcription unavailable (model download failed)."
        )
        return True

    await update.message.reply_text("🎧 Transcribing... (this may take a minute)")
    asyncio.create_task(_process_voice(update, context, model, on_text_ready))
    return True


async def _process_voice(update, context, model, on_text_ready):
    file_path = None
    try:
        voice_file = await update.message.voice.get_file()
        file_path = Path(f"tmp/voice_{update.message.message_id}.ogg")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await voice_file.download_to_drive(file_path)

        segments, _ = model.transcribe(str(file_path), beam_size=5)
        text = " ".join(segment.text for segment in segments).strip()
        if not text:
            await update.message.reply_text(
                "⚠️ Could not extract speech from voice message"
            )
            return

        await update.message.reply_text(
            f'📝 Heard: "{text}"\n\n⚠️ Transcription may be inaccurate for noisy audio.'
        )
        await on_text_ready(text)
    except Exception as exc:
        await update.message.reply_text(f"❌ Transcription failed: {exc}")
    finally:
        if file_path is not None:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass
