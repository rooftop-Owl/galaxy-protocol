import asyncio
import importlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

common = importlib.import_module("handlers.common")


_RATE_LIMIT = defaultdict(list)


def feature_enabled(config):
    return bool(config.get("features", {}).get("GALAXY_IMAGE_PDF_ENABLED", False))


def _allow_upload(user_id):
    now = datetime.now(timezone.utc)
    recent = [ts for ts in _RATE_LIMIT[user_id] if now - ts < timedelta(minutes=5)]
    _RATE_LIMIT[user_id] = recent
    if len(recent) >= 5:
        return False
    _RATE_LIMIT[user_id].append(now)
    return True


async def handle_photo(update, context, config, machine_config):
    if not feature_enabled(config) or not update.message.photo:
        return False

    user_id = update.effective_user.id
    if not _allow_upload(user_id):
        await update.message.reply_text("⏳ Rate limit: 5 files per 5 minutes")
        return True

    await update.message.reply_text("🔍 Extracting text... (this may take a minute)")
    asyncio.create_task(_process_photo(update, machine_config))
    return True


async def handle_pdf(update, context, config, machine_config):
    if not feature_enabled(config):
        return False

    doc = update.message.document
    if not doc:
        return False
    if not (doc.file_name or "").lower().endswith(".pdf"):
        return False

    user_id = update.effective_user.id
    if not _allow_upload(user_id):
        await update.message.reply_text("⏳ Rate limit: 5 files per 5 minutes")
        return True

    await update.message.reply_text("📖 Reading PDF... (this may take a minute)")
    asyncio.create_task(_process_pdf(update, machine_config))
    return True


async def _process_photo(update, machine_config):
    file_path = None
    try:
        photo_file = await update.message.photo[-1].get_file()
        file_path = Path(f"tmp/photo_{update.message.message_id}.jpg")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await photo_file.download_to_drive(file_path)

        text = _ocr_text(file_path)
        refs_dir = common.references_dir_for_machine(machine_config)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        ref_path = common.write_reference_markdown(
            refs_dir / f"{date}-image-ocr-{stamp}.md",
            "Image OCR Capture",
            file_path.name,
            text or "No text extracted.",
            {"Type": "image", "Processor": "tesseract"},
        )
        await update.message.reply_text(
            f"✅ Added OCR reference\n📁 Saved to {ref_path.name}"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ OCR failed: {exc}")
    finally:
        if file_path is not None:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass


async def _process_pdf(update, machine_config):
    file_path = None
    try:
        doc = update.message.document
        pdf_file = await doc.get_file()
        file_path = Path(f"tmp/{update.message.message_id}-{doc.file_name}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await pdf_file.download_to_drive(file_path)

        text = _extract_pdf_text(file_path)
        refs_dir = common.references_dir_for_machine(machine_config)
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        ref_path = common.write_reference_markdown(
            refs_dir / f"{date}-pdf-{stamp}.md",
            doc.file_name or "PDF Capture",
            doc.file_name or "pdf",
            text or "No text extracted.",
            {"Type": "pdf", "Processor": "pdfplumber"},
        )
        await update.message.reply_text(
            f"✅ Added PDF reference\n📁 Saved to {ref_path.name}"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ PDF extraction failed: {exc}")
    finally:
        if file_path is not None:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass


def _ocr_text(image_path):
    try:
        cv2 = importlib.import_module("cv2")
        np = importlib.import_module("numpy")
        pytesseract = importlib.import_module("pytesseract")
        from PIL import Image

        image = Image.open(image_path)
        cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        thresholded = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[
            1
        ]
        return pytesseract.image_to_string(thresholded).strip()
    except Exception:
        pytesseract = importlib.import_module("pytesseract")
        from PIL import Image

        return pytesseract.image_to_string(Image.open(image_path)).strip()


def _extract_pdf_text(pdf_path):
    docker = importlib.import_module("docker")

    client = docker.from_env()
    command = (
        "pip install -q pdfplumber && "
        'python -c "import pdfplumber;'
        f"pdf=pdfplumber.open('/input/{pdf_path.name}');"
        "print('\\n\\n'.join((p.extract_text() or '') for p in pdf.pages))\""
    )
    output = client.containers.run(
        "python:3.11-slim",
        ["sh", "-lc", command],
        volumes={str(pdf_path.parent.resolve()): {"bind": "/input", "mode": "ro"}},
        remove=True,
        mem_limit="512m",
        cpu_quota=50000,
        network_disabled=True,
    )
    return output.decode("utf-8", errors="replace").strip()
