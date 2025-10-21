import os
from pathlib import Path
import mido
from pydub import AudioSegment
import eyed3
import chardet
import re

# Define supported extensions
SUPPORTED_AUDIO_EXTENSIONS = ['.mp3', '.wav', '.flac', '.m4a', '.aac']
SUPPORTED_MIDI_EXTENSIONS = ['.mid', '.midi']
SUPPORTED_LYRICS_EXTENSIONS = ['.txt']

def _get_file_encoding(file_path):
    """
    Detects the encoding of a text file by reading the first 1KB.
    This is efficient as encoding information is typically at the start of the file.
    """
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read(1024)) # Read first 1KB for efficiency
    return result['encoding']

def _validate_midi(file_path):
    """
    Checks if a file is a valid MIDI file by attempting to parse it with mido.
    Returns True if successful, False otherwise.
    """
    try:
        mido.MidiFile(file_path)
        return True
    except Exception:
        return False

def _validate_audio(file_path):
    """
    Checks if a file is a valid audio file by attempting to load its metadata.
    This is a quick check that avoids decoding the entire file.
    """
    try:
        # eyed3 is often more reliable for a quick, non-decoding check of MP3s.
        if Path(file_path).suffix.lower() == '.mp3':
            if eyed3.load(file_path) is None:
                return False
        # For other formats, pydub is a good general-purpose checker.
        else:
            AudioSegment.from_file(file_path)
        return True
    except Exception:
        return False

def classify_and_validate_files(directory):
    """
    Scans a directory, classifies files by type (audio, midi, lyrics), performs
    basic validation on each, and returns a dictionary of the classified files.
    """
    classified_files = {
        'audio': [],
        'midi': [],
        'lyrics': [],
        'unsupported': []
    }
    
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        if not os.path.isfile(file_path):
            continue

        file_ext = Path(filename).suffix.lower()
        
        if file_ext in SUPPORTED_AUDIO_EXTENSIONS and _validate_audio(file_path):
            classified_files['audio'].append({'path': file_path})
            print(f"  [OK] Audio: {filename}")
        elif file_ext in SUPPORTED_MIDI_EXTENSIONS and _validate_midi(file_path):
            classified_files['midi'].append({'path': file_path})
            print(f"  [OK] MIDI: {filename}")
        elif file_ext in SUPPORTED_LYRICS_EXTENSIONS:
            encoding = _get_file_encoding(file_path)
            classified_files['lyrics'].append({'path': file_path, 'encoding': encoding})
            print(f"  [OK] Lyrics: {filename} (encoding: {encoding})")
        else:
            classified_files['unsupported'].append({'path': file_path})
            print(f"  [WARN] Unsupported or corrupt: {filename}")
            
    return classified_files

def parse_title_and_stem_from_filenames(classified_files):
    """
    Parses filenames to extract a song title and stem name based on common
    conventions (e.g., from AI music generators). It modifies the file info
    dictionaries in place.
    
    Example patterns:
    - "My Song (Vocals).wav" -> title: "My Song", stem: "vocals"
    - "Another Song - Bass.mp3" -> title: "Another Song", stem: "bass"
    """
    # This regex looks for a title followed by either "(stem)" or " - stem".
    # It requires spaces around the hyphen to avoid splitting hyphenated words in titles.
    pattern = re.compile(r"^(?P<title>.+?)\s*(?:\((?P<stem_paren>[^)]+)\)|\s+-\s+(?P<stem_hyphen>.+?))$")

    print("\nParsing filenames for Song Title and Stem...")
    
    # We only parse audio and midi files for stems
    for file_type in ['audio', 'midi']:
        for file_info in classified_files[file_type]:
            filename_stem = Path(file_info['path']).stem
            match = pattern.match(filename_stem)
            
            title = filename_stem
            stem = 'full_mix' # Default if no pattern matches
            
            if match:
                title = match.group('title').strip()
                stem = (match.group('stem_paren') or match.group('stem_hyphen')).strip().lower()

            file_info['title'] = title
            file_info['stem'] = stem
            print(f"  -> Parsed '{Path(file_info['path']).name}': Title='{title}', Stem='{stem}'")

    return classified_files

def find_common_title(filenames: list[str]) -> str:
    """
    Finds a user-friendly project title from a list of filenames.
    
    It determines the title by finding the longest common prefix among all filenames,
    then cleans up common separators. If no meaningful common prefix is found,
    it returns a generic "Untitled Project".
    """
    if not filenames:
        return "Untitled Project"

    stems = [Path(f).stem for f in filenames]

    if len(stems) == 1:
        return stems[0]

    common_prefix = os.path.commonprefix(stems)

    if common_prefix:
        # Clean up trailing characters that are often part of separators
        cleaned_title = common_prefix.rstrip(' _-(').strip()
        # Ensure the common prefix is meaningful and not just a single character
        if len(cleaned_title) > 2: # Avoid very short, meaningless prefixes
            return cleaned_title

    # Fallback for unrelated files or very short common prefixes
    return "Untitled Project"

def group_files_as_single_project(parsed_files, original_music_filenames: list[str], quiet: bool = False):
    """
    Takes all classified files and groups them under a single project title.
    The title is determined by finding a common prefix among the music filenames,
    ensuring a sensible name for multi-file uploads (e.g., a set of stems).
    """
    display_title = find_common_title(original_music_filenames)
    if not quiet:
        print(f"\nConsolidating all files into a single project with display title: '{display_title}'")
    
    return {display_title: parsed_files}
