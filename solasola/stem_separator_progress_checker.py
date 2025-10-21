import re
import logging


class DemucsProgressParser:
    """
    Parses the real-time stdout of the Demucs subprocess to extract structured
    progress updates. This encapsulates the fragile parsing logic, separating
    it from the main processing flow.
    """
    def __init__(self, model_name: str):
        self.is_ensemble = model_name == 'htdemucs_ft'
        self.num_models = 4 if self.is_ensemble else 1
        self.progress_pattern = re.compile(r'(\d+)%\|')
        self.line_buffer = ""
        self.phase = 'unknown'  # 'download' or 'separate'
        self.download_count = 0
        self.separation_model_index = 0
        self.last_reported_progress = -1

    def parse_line(self, line: str) -> dict | None:
        """
        Parses a single line of output and returns a dictionary with progress info if found.
        
        Returns: A dictionary like {'stage': 4, 'sub_stage': 1, 'progress':
        10, 'message': '...'} or None.
        """
        stripped_line = line.strip()
        if not stripped_line:
            return None

        # Use logging.debug to show raw Demucs output only when in debug mode. # noqa
        # This keeps the production log clean while allowing for detailed
        # debugging.
        logging.debug(f"  -> [Demucs Raw] {stripped_line}")

        if "Downloading:" in stripped_line:
            self.phase = 'download'
            self.download_count += 1
            return {
                'stage': 3, 'sub_stage': 1, 'progress': 50,
                'message': f"Downloading model file {self.download_count}..."
            }

        elif "Separating track" in stripped_line:
            self.phase = 'separate'
            self.separation_model_index = 0 # Reset for each separation run

        match = self.progress_pattern.search(stripped_line) # noqa
        if match and self.phase == 'separate':
            progress = int(match.group(1))
            if progress == 0 and self.last_reported_progress > 90:
                self.separation_model_index += 1
            
            sub_stage_index = self.separation_model_index + 1
            message = (f"Ensemble processing ({min(sub_stage_index, self.num_models)}/{self.num_models}) - {progress}%" if self.is_ensemble else f"Separating instruments ({progress}%)") # noqa
            self.last_reported_progress = progress
            return {'stage': 4, 'sub_stage': sub_stage_index,
                    'progress': progress, 'message': message}

        return None
