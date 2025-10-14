from music21 import environment, converter, metadata, stream
from pathlib import Path
import subprocess
import os
import traceback


def _post_process_abc_content(abc_text: str, title: str) -> str:
    """Cleans midi2abc output, sets title, removes comments."""
    lines = abc_text.splitlines()
    cleaned_lines = []
    seen_midi_program_in_voice = False

    for line in lines:
        # The midi2abc tool generates a default title from the filename.
        if line.startswith('T:'):
            cleaned_lines.append(f'T: {title}')
            continue

        if line.strip().startswith('% Last note suggests'):
            continue

        if line.strip().startswith('V:'):
            seen_midi_program_in_voice = False
        if line.strip().startswith('%%MIDI program'):
            if not seen_midi_program_in_voice:
                seen_midi_program_in_voice = True
                cleaned_lines.append(line)
            continue

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def convert_midi_to_abc(
    midi_paths: list, song_title: str
) -> dict[str, str] | None:
    """Converts MIDI files to a dictionary of ABC strings."""
    us = environment.UserSettings()
    us['directoryScratch'] = '/tmp'

    temp_dir = Path(us['directoryScratch'])

    abc_results = {}

    for midi_path in midi_paths:
        part_name = Path(midi_path).stem
        part_title = f"{song_title} ({part_name})"
        print(f"  -> Processing part: {part_name}.mid")

        temp_midi_path = temp_dir / f"{part_title}.mid"
        temp_abc_path = temp_dir / f"{part_title}.abc"

        try:
            score_part = converter.parse(midi_path, forceSource=True)
            if not score_part or not score_part.flatten().notesAndRests:
                print(f"    -> Skipping empty MIDI: {Path(midi_path).name}") # noqa
                continue

            single_part_score = stream.Score()
            single_part_score.insert(0, metadata.Metadata())
            single_part_score.metadata.title = part_title
            score_part.parts[0].id = part_name
            single_part_score.insert(0, score_part.parts[0])

            single_part_score.write('midi', fp=str(temp_midi_path))

            cmd = ['midi2abc', str(temp_midi_path),
                   '-o', str(temp_abc_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                print(f"  -> ERROR: midi2abc failed for {part_name}: "
                      f"{result.stderr}")
                continue

            if not temp_abc_path.exists() or temp_abc_path.stat().st_size == 0:
                print(f"  -> ERROR: midi2abc created an empty file for {part_name}.")
                continue

            with open(temp_abc_path, 'r', encoding='utf-8') as f:
                abc_text_content = f.read()

            abc_results[part_name] = _post_process_abc_content(
                abc_text_content, part_title)
            print(f"  -> Successfully converted {part_name} to ABC.")

        except Exception as e:
            print(
                f"  -> ERROR during ABC conversion for {part_name}: {e}")
            traceback.print_exc()
        finally:
            if temp_midi_path.exists():
                os.remove(temp_midi_path)
            if temp_abc_path.exists():
                os.remove(temp_abc_path)

    return abc_results if abc_results else None


def generate_mix_abc(mix_midi_path: str, song_title: str) -> str | None:
    """Generates ABC notation for a single 'mix' MIDI file."""
    us = environment.UserSettings()
    us['directoryScratch'] = '/tmp'
    temp_dir = Path(us['directoryScratch'])
    mix_title = f"{song_title} (Mix)"
    temp_abc_path = temp_dir / f"{mix_title}.abc"

    try:
        print("\n  -> Creating combined 'Mix' ABC score...")
        cmd = ['midi2abc', mix_midi_path, '-o', str(temp_abc_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode == 0 and temp_abc_path.exists():
            raw_mix_abc = temp_abc_path.read_text(encoding='utf-8')
            cleaned_mix_abc = _post_process_abc_content(raw_mix_abc, mix_title)
            print("  -> Successfully created 'Mix' ABC.")
            return cleaned_mix_abc
        else:
            print(
                f"  -> ERROR: midi2abc failed for Mix: {result.stderr}")
            return None
    except Exception as e:
        print(f"  -> ERROR during Mix ABC conversion: {e}")
        return None
    finally:
        if temp_abc_path.exists():
            os.remove(temp_abc_path)
