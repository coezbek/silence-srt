# remove_silences.py

import argparse
import pathlib
import auditok
import logging
import os
import glob
import shutil # For potential backup if overwriting

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler() # Output to console
    ]
)

def process_file(filepath: str, args: argparse.Namespace) -> bool:
    """
    Processes a single WAV file to remove leading and trailing silences.

    Args:
        filepath: Path to the input WAV file.
        args: Command-line arguments.

    Returns:
        True if the file was modified (or would be in dry run), False otherwise.
    """
    logging.debug(f"Processing: {filepath}")
    modified = False

    try:
        # Load the original audio to get its full duration for comparison
        # and to ensure we use its original properties (sr, sample_width, channels)
        original_audio_full = auditok.load(filepath)

        # `split` returns a generator of AudioRegion objects
        # These regions represent continuous audio events.
        audio_regions = list(auditok.split(
            original_audio_full,
            min_dur=args.min_event_duration,         # Minimum duration of a valid audio event
            max_dur=args.max_event_duration,         # Maximum duration of an event
            max_silence=args.max_silence_within_event, # Max tolerated silence *within* an event
            energy_threshold=args.energy_threshold,  # Detection threshold
            analysis_window=args.analysis_window_s   # Analysis window for energy calculation
        ))

        if not audio_regions:
            logging.warning(f"No audio events detected in {filepath} above threshold. File might be entirely silent or too quiet. Skipping.")
            if args.output_dir:
              output_filepath = os.path.join(args.output_dir, os.path.basename(filepath))
              shutil.copy2(filepath, output_filepath)
              logging.info(f"Saved unmodified audio to: {output_filepath}")
            return False
        
        original_duration = original_audio_full.duration

        # The first sound starts at the beginning of the first region, but never before 0.0
        first_sound_start_time = max(0.0, audio_regions[0].start - args.analysis_window_s)

        # The last sound ends at the end of the last region, but never after the original duration
        last_sound_end_time = min(original_duration, audio_regions[-1].end + args.analysis_window_s)

        # Define a small tolerance, e.g., based on analysis window,
        # to avoid trimming if the silence is negligible.
        tolerance = args.analysis_window_s # Allow for slight detection variations

        needs_front_trimming = False
        needs_back_trimming = False
        if first_sound_start_time >= tolerance:
            needs_front_trimming = True
            logging.debug(f"{filepath}: Leading silence detected. Audio starts at {first_sound_start_time:.3f}s.")
        else:
            first_sound_start_time = 0.0 # No leading silence
        
        enable_trailing_trimming = False
        if enable_trailing_trimming and (original_duration - last_sound_end_time) >= tolerance:
            needs_back_trimming = True
            logging.debug(f"{filepath}: Trailing silence detected. Audio ends at {last_sound_end_time:.3f}s (original duration {original_duration:.3f}s).")
        else:
            last_sound_end_time = original_duration # No trailing silence

        if not (needs_front_trimming or needs_back_trimming):
            logging.info(f"No significant leading/trailing silence to remove in {filepath}. Skipping modification.")
            if args.output_dir:
              output_filepath = os.path.join(args.output_dir, os.path.basename(filepath))
              shutil.copy2(filepath, output_filepath)
              logging.info(f"Saved unmodified audio to: {output_filepath}")

            return False

        # This file needs to be modified
        logging.info(f"MODIFICATION NEEDED for {filepath}: "
                     f"Original duration: {original_duration:.3f}s. "
                     f"Content from {first_sound_start_time:.3f}s to {last_sound_end_time:.3f}s.")
        modified = True

        if args.dry_run:
            logging.info(f"[DRY RUN] Would trim {filepath} to new duration: {last_sound_end_time - first_sound_start_time:.3f}s.")
            return True

        # Determine output path
        if args.output_dir:
            output_filepath = os.path.join(args.output_dir, os.path.basename(filepath))
        else:
            # Overwrite original file (consider adding a backup option)
            if args.backup:
                # Prepend .bak before the file extension
                path = pathlib.Path(filepath)
                suffix = path.suffix
                backup_filepath = path.with_suffix(f".bak{suffix}")

                logging.info(f"Backing up original file to {backup_filepath}")
                shutil.copy2(filepath, backup_filepath)
            output_filepath = filepath

        # Calculate the duration of the content to keep
        content_duration = last_sound_end_time - first_sound_start_time
        if content_duration <= 0:
            logging.warning(f"Calculated content duration for {filepath} is zero or negative ({content_duration:.3f}s). "
                            f"This might happen if detection parameters are very strict or file is very short. Skipping save.")
            return False # Effectively not modified if we don't save

        # Create a new AudioRegion representing the trimmed audio
        trimmed_audio_region = auditok.load(
            filepath,
            skip=first_sound_start_time,
            max_read=content_duration
        )

        # Save the trimmed audio
        trimmed_audio_region.save(output_filepath)
        logging.info(f"Saved trimmed audio to: {output_filepath}")
        return True

    except auditok.exceptions.PyAVError as e:
        logging.error(f"Auditok (PyAV) error processing {filepath}: {e}. Ensure ffmpeg is installed and accessible, and the file is a valid audio format.")
        return False
    except Exception as e:
        logging.error(f"Unexpected error processing {filepath}: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Removes leading and trailing silences from WAV files using auditok. "
                    "Logs files that are modified."
    )
    parser.add_argument(
        "input_files",
        nargs='+',
        help="One or more .wav files or a glob pattern (e.g., 'audio_files/*.wav'). "
             "Ensure patterns are quoted if they might be expanded by the shell."
    )
    parser.add_argument(
        "-o", "--output-dir", "--outdir",
        type=str,
        default=None,
        help="Optional directory to save modified files. If not provided, original files are overwritten."
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=True,
        help="Create a .bak copy of the original file before overwriting (default)."
    )
    parser.add_argument(
        "--no-backup",
        action="store_false",
        dest="backup", 
        help="Disable backups."
    )

    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore original files from .bak backups and exit."
    )

    # Auditok parameters (similar to the provided script)
    parser.add_argument(
        "-t", "--energy-threshold",
        default=45, # auditok's default, adjust as needed. Original script used 40.
        type=float, # auditok uses float for threshold
        help="Energy threshold for detecting audio events. Higher values detect only louder sounds. (default: 50)"
    )
    parser.add_argument(
        "-m", "--min-event-duration",
        default=0.1, # seconds
        type=float,
        help="Minimum duration of a valid audio event in seconds. (default: 0.1)"
    )
    parser.add_argument(
        "-M", "--max-event-duration",
        default=60*60, # 1 hour, effectively no limit for most cases
        type=float,
        help="Maximum duration of a single audio event in seconds. (default: 3600)"
    )
    parser.add_argument(
        "--max-silence-within-event",
        default=0.3, # seconds. Original script used 0.05.
        type=float,
        help="Maximum tolerated silence duration *within* an audio event (bridges short gaps). (default: 0.3)"
    )
    parser.add_argument(
        "--analysis-window-s",
        default=0.01, # seconds (10 ms)
        type=float,
        help="Analysis window duration in seconds for energy calculation. (default: 0.01)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform analysis and log what would be changed, but do not modify any files."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging."
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.dry_run:
        logging.info("--- DRY RUN MODE ENABLED: No files will be modified. ---")

    if args.backup and args.output_dir:
        args.backup = False
        logging.warning("--backup option is ignored when --output-dir is specified, as originals are not overwritten.")

    if args.restore:
      restored_count = 0
      for pattern in args.input_files:
          for original_path in glob.glob(pattern):
              
              path = pathlib.Path(original_path)
              suffix = path.suffix
              bak_path = path.with_suffix(f".bak{suffix}")
              
              if os.path.exists(bak_path):
                  shutil.move(bak_path, original_path)
                  logging.info(f"Restored: {original_path}")
                  restored_count += 1
              else:
                  logging.warning(f"Backup not found: {bak_path}")
      logging.info(f"--- Restore Complete: {restored_count} file(s) restored. ---")
      return

    # Expand glob patterns and collect all file paths
    all_filepaths = []
    for pattern in args.input_files:
        expanded_paths = glob.glob(pattern)
        if not expanded_paths:
            logging.warning(f"No files found matching pattern: {pattern}")
        all_filepaths.extend(expanded_paths)

    if not all_filepaths:
        logging.info("No input files to process.")
        return

    # Deduplicate (in case patterns overlap)
    unique_filepaths = sorted(list(set(all_filepaths)))

    modified_files_count = 0
    processed_files_count = 0

    if args.output_dir:
      if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
        logging.info(f"Created output directory: {args.output_dir}")

    for filepath in unique_filepaths:
        if not os.path.isfile(filepath):
            logging.warning(f"Path is not a file, skipping: {filepath}")
            continue
        if not filepath.lower().endswith(".wav"):
            logging.warning(f"File does not end with .wav, skipping: {filepath}. Auditok might support other formats if ffmpeg is available.")
            # Continue if you want to try other formats, but WAV is specified
            # continue # Uncomment to strictly enforce WAV

        processed_files_count += 1
        if process_file(filepath, args):
            modified_files_count += 1

    logging.info(f"--- Processing Complete ---")
    logging.info(f"Total files scanned: {processed_files_count}")
    if args.dry_run:
        logging.info(f"Files that would be modified: {modified_files_count}")
    else:
        logging.info(f"Files modified: {modified_files_count}")

if __name__ == "__main__":
    main()