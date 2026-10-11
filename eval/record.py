import json
from collections.abc import Callable
from pathlib import Path

from client_pc.client import Player, Recorder
from eval import config


def clip_path(question_id: str) -> Path:
    return config.CLIP_DIR / f"{question_id}.wav"


def pending(questions: list[dict]) -> list[dict]:
    return [q for q in questions if not clip_path(q["id"]).exists()]


def record_question(
    question: dict,
    recorder: Recorder,
    player: Player,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> bool:
    """Record one clip until it is kept; False if the user quit instead."""
    while True:
        say(f"[{question['id']}] {question['spoken']}")
        ask("Press ENTER to start recording")
        recorder.start_recording()
        ask("Recording... press ENTER to stop")
        wav = recorder.stop_recording()
        if wav is None:
            say("Nothing was recorded, try again.")
            continue
        choice = _review(wav, player, ask)
        if choice == "keep":
            config.CLIP_DIR.mkdir(parents=True, exist_ok=True)
            clip_path(question["id"]).write_bytes(wav)
            return True
        if choice == "quit":
            return False


def _review(wav: bytes, player: Player, ask: Callable[[str], str]) -> str:
    while True:
        answer = ask("ENTER keep, p play, r redo, q quit").strip().lower()
        if answer == "p":
            player.play_wav(wav)
        elif answer in ("", "r", "q"):
            return {"": "keep", "r": "redo", "q": "quit"}[answer]


def main() -> None:
    questions = json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
    todo = pending(questions)
    if not todo:
        print(f"All {len(questions)} clips are recorded.")
        return
    recorder, player = Recorder(), Player()
    recorder.open()
    player.open()
    try:
        for n, question in enumerate(todo, 1):
            print(f"\nQuestion {n} of {len(todo)}")
            if not record_question(question, recorder, player, ask=input):
                break
    finally:
        recorder.close()
        player.close()


if __name__ == "__main__":
    main()
