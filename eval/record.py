import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from client_pc.client import Player, Recorder
from eval import config


def clip_path(question_id: str, clip_dir: Path | None = None) -> Path:
    return (clip_dir or config.CLIP_DIR) / f"{question_id}.wav"


def pending(questions: list[dict], clip_dir: Path | None = None) -> list[dict]:
    return [q for q in questions if not clip_path(q["id"], clip_dir).exists()]


def v2_items(data: dict) -> list[dict]:
    """The v2 clips to record in file order: follow-up second turns, one quiz start."""
    items, quiz_start_added = [], False
    for row in data["rows"]:
        if row["group"] == "quiz" and not quiz_start_added:
            items.append({"id": "quiz_start", "spoken": data["quiz_start"]})
            quiz_start_added = True
        items.append({"id": row["id"], "spoken": row["spoken"]})
        if row["group"] == "followup":
            items.append({"id": f"{row['id']}_2", "spoken": row["followup"]})
    return items


def record_question(
    question: dict,
    recorder: Recorder,
    player: Player,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    clip_dir: Path | None = None,
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
            path = clip_path(question["id"], clip_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav)
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


def main(argv: Sequence[str] = ()) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--set", choices=["v1", "v2"], default="v1", dest="question_set"
    )
    args = parser.parse_args(argv)
    if args.question_set == "v2":
        data = json.loads(config.QUESTIONS_V2_PATH.read_text(encoding="utf-8"))
        questions, clip_dir = v2_items(data), config.CLIP_DIR_V2
    else:
        questions = json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
        clip_dir = None
    todo = pending(questions, clip_dir)
    if not todo:
        print(f"All {len(questions)} clips are recorded.")
        return
    recorder, player = Recorder(), Player()
    recorder.open()
    player.open()
    try:
        for n, question in enumerate(todo, 1):
            print(f"\nQuestion {n} of {len(todo)}")
            if not record_question(
                question, recorder, player, ask=input, clip_dir=clip_dir
            ):
                break
    finally:
        recorder.close()
        player.close()


if __name__ == "__main__":
    main(sys.argv[1:])
