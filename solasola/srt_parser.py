import re
from datetime import timedelta


def srt_time_format(seconds: float) -> str:
    """Converts seconds to SRT time format HH:MM:SS,ms"""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        seconds = 0
    millisec = int((seconds - int(seconds)) * 1000)
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d},{millisec:03d}"


def _parse_srt_time(time_str: str) -> float: # noqa
    """Converts an SRT time string (HH:MM:SS,ms) to a total number of
    seconds."""
    h, m, s, ms = map(int, re.split('[:,]', time_str))
    return timedelta(hours=h, minutes=m, seconds=s, milliseconds=ms).total_seconds()

def parse_srt_file(srt_content: str) -> list:
    """
    Parses SRT content from a string and returns a list of lyric events.

    Args:
        srt_content (str): The string content of the SRT file.

    Returns:
        A list of dictionaries, where each dict is {'start': ..., 'end': ..., 'text': ...}.
    """
    parsed_segments = []
    try:
        # Split the content by blank lines to get individual subtitle blocks
        blocks = re.split(r'\n\s*\n', srt_content.strip())

        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 2 and '-->' in lines[1]:
                time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', lines[1])
                if time_match:
                    start_sec = _parse_srt_time(time_match.group(1))
                    end_sec = _parse_srt_time(time_match.group(2))
                    text = " ".join(lines[2:])
                    parsed_segments.append({'start': start_sec, 'end': end_sec, 'text': text})
        return parsed_segments
    except Exception as e:
        print(f"  -> Error parsing SRT content: {e}")
        return []


def generate_srt_from_txt(txt_content: str, total_duration: float) -> tuple[str, list]:
    """
    Generates SRT content and parsed segments from plain text content,
    distributing it evenly over a given duration.

    Returns:
        A tuple containing (srt_string, parsed_segments_list).
    """
    lines = [line.strip() for line in txt_content.splitlines() if line.strip()]
    num_lines = len(lines)
    if num_lines == 0 or total_duration <= 0:
        return "", []

    duration_per_line = total_duration / num_lines
    srt_blocks_str = []
    parsed_segments = []
    for i, line_text in enumerate(lines):
        start_time = i * duration_per_line
        end_time = (i + 1) * duration_per_line if i < num_lines - 1 else total_duration
        srt_blocks_str.append(f"{i+1}\n{srt_time_format(start_time)} --> {srt_time_format(end_time)}\n{line_text}\n\n")
        parsed_segments.append({'start': start_time, 'end': end_time, 'text': line_text})
    
    final_srt_content = "".join(srt_blocks_str).strip()
    return final_srt_content, parsed_segments


def create_srt_from_txt_file(file_path: str, encoding: str, total_duration: float) -> tuple[str, str, list] | tuple[None, None, None]: # noqa
    """
    Reads a text file and generates SRT content from it. This is the main
    entry point for converting a .txt file.

    Returns:
        A tuple of (final_srt_content, original_text, parsed_segments) or (None, None, None) on failure.
    """
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            user_lyrics_text = f.read()

        final_srt_content, parsed_segments = generate_srt_from_txt(user_lyrics_text, total_duration)

        return final_srt_content, user_lyrics_text, parsed_segments
    except Exception as e:
        print(f"  -> Error processing lyrics file {file_path}: {e}")
        return None, None, None