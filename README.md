# PDF AI Assistant

A local Windows desktop app for asking questions about your PDFs. Answers are written from retrieved passages, and each answer keeps the file name and page it came from.

The interface is PySide6. PDF text, chunking, embeddings, and search all run on your computer. Only a question and the short passages needed to answer it are sent to the AI service you configure.

## What you need

- Windows 10 or 11 for the packaged app. The same code also runs on macOS for development.
- Python 3.11
- An OpenAI-compatible API key, or a local server such as LM Studio or Ollama

## Install

```bash
cd pdf_ai_assistant
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure the AI service

Start the app and open **Settings**.

| Field | Example |
| --- | --- |
| API key | Optional. Leave it blank to use the built-in Gemini key. A key you type is stored in the system keychain and replaces it. |
| Model | `gpt-4o-mini` |
| API endpoint | `https://api.openai.com/v1` |
| How much the wording can vary | `0.1` — lower stays closer to the pages |
| Longest reply | about 600 words |

Local servers that speak the OpenAI chat API work the same way:

- LM Studio: endpoint `http://localhost:1234/v1`, any non-empty key such as `local`, and the model name LM Studio shows
- Ollama: endpoint `http://localhost:11434/v1`, key `local`, model such as `llama3.1`

Use **Test connection** before you rely on a new endpoint.

Retrieval defaults, also in Settings:

| Setting | Default |
| --- | --- |
| Passage length | 900 characters |
| Repeated edges | 150 characters |
| Passages per question | 5 |
| How close a match must be | 35% |
| Also look for the same words | on |

Passage length and repeated edges apply the next time you add a PDF, or when you choose **Reindex all documents**.

Embeddings use the local model `BAAI/bge-small-en-v1.5`. The first PDF you add downloads it into the app data folder. Document text is not sent anywhere to build the index.

## Run

```bash
python main.py
```

You do not need a terminal after the app has been packaged.

## How an answer is produced

1. Text is extracted per page. Password-protected PDFs ask for a password. Scanned PDFs use Tesseract when it is installed.
2. Text is cleaned and split into passages that stay on one page.
3. Passages are embedded locally and stored in a FAISS index. SQLite keeps the text, file name, and page.
4. A question is embedded and matched. Keyword search can boost unusual words.
5. If the closest passage is below the similarity threshold, the app does not call the model. It says: `I couldn't find enough information in the uploaded documents to answer this question.`
6. Otherwise the model sees only those passages and must return JSON that cites them. A reply that is not grounded in the passages is replaced with the same not-found sentence.

Chats remember which documents were checked. You can rename, delete, or clear a chat, and export it to text or PDF.

**Compare documents** takes two PDFs and shows a topic table.

## Where files are stored

| System | Location |
| --- | --- |
| Windows | `%APPDATA%\PDF AI Assistant` |
| macOS | `~/Library/Application Support/PDF AI Assistant` |

That folder holds `app.db`, `index.faiss`, and copies of the PDFs you add. Settings can open the folder, reindex, or clear the indexed documents. Chat history is kept when you clear the index.

## Scanned PDFs

If a PDF has no text layer, install [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) and add the file again. Without Tesseract, that file is reported as scanned and the rest of the library is left alone.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`scripts/smoke_rag.py` indexes a sample PDF with the real embedding model. It does not call an AI API.

## Build a Windows executable

Build on Windows. A `.exe` cannot be produced from macOS.

```bat
pip install pyinstaller
pyinstaller --noconfirm PDF-AI-Assistant.spec
```

Or run `scripts\build_windows.ps1`.

The packaged app is `dist\PDF-AI-Assistant.exe`. It opens as a window, with no console. The first launch can take longer while the embedding model is unpacked and, if needed, downloaded.

## Fonts

Fraunces, Figtree, and IBM Plex Mono are bundled under the SIL Open Font License. See `assets/fonts/OFL.txt` and `assets/fonts/NOTICE.txt`.
