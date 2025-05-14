import argparse
import auditok
import re
import logging
import os


# SRT time format is HH:MM:SS,mmm or HH:MM:SS.mmm
def time_to_seconds(time_str: str) -> float:
    """Converts time from HH:MM:SS,mmm or HH:MM:SS.mmm format to seconds."""
    # Allow comma or dot separator for milliseconds
    match = re.match(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d+)", time_str)
    if not match:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds, ms_str = match.groups()
    ms = int(ms_str.ljust(3, '0')[:3])
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + ms / 1000.0

def parse_srt(srt_path: str) -> list:
    """Parses an SRT file using the original regex approach."""
    segments = []
    try:
        with open(srt_path, 'r', encoding='utf-8') as file:
            content = file.read()
        # Use original regex, slightly adapted lookahead for EOF robustness
        srt_pattern = re.compile(r"""(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.+?)\n*(?=\d+\n\d{2}:\d{2}:\d{2},\d{3}|\Z)""", re.DOTALL | re.MULTILINE)
        for match in srt_pattern.finditer(content):
            try:
                segments.append({
                    'index': int(match.group(1)),
                    'start_time': time_to_seconds(match.group(2)),
                    'end_time': time_to_seconds(match.group(3)),
                    'text': match.group(4).strip().replace('\n', ' ') # Clean text
                })
            except ValueError as e:
                logging.warning(f"Skipping segment {match.group(1)} due to time parse error: {e}")
    except FileNotFoundError:
        logging.error(f"SRT file not found: {srt_path}")
    except Exception as e:
        logging.error(f"Error reading/parsing SRT {srt_path}: {e}")
    segments.sort(key=lambda x: x['index']) # Ensure order
    return segments

def seconds_to_srt_time(seconds: float) -> str:
    """Converts seconds to SRT time format HH:MM:SS,mmm or HH:MM:SS.mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{int(seconds):02},{milliseconds:03}"

def main(args):

    analysis_window = 0.01 # 10 ms    

    # `split` returns a generator of AudioRegion objects
    audio_events = auditok.split(
        args.input,      # Input audio file
        min_dur=args.min_dur, # Minimum duration of a valid audio event in seconds
        max_dur=args.max_dur, # Maximum duration of an event
        max_silence=0.05, # Maximum tolerated silence duration within an event
        analysis_window=analysis_window,
        energy_threshold=args.threshold, # Detection threshold
    )

    audio_events = list(audio_events)

    print(f"Detected {len(audio_events)} audio events in {args.input}")

    # Save the events to a .srt file
    output_file = args.output

    cur_pos = 0.0
    region_id = 1

    silence_segments = []
    # audio_segments = []

    with open(output_file, "w") as f:

        if args.file_to_fix is None:
            print(f"Writing silence segments to {output_file}")

        for i, r in enumerate(audio_events):

            # audio_segments.append((r.start - analysis_window, r.end + analysis_window))

            if args.negate:           
                # Write the start and end times of each event to the file
                f.write(f"{i+1}\n")
                f.write(f"{seconds_to_srt_time(r.start)} --> {seconds_to_srt_time(r.end)}\n")
                f.write(f"Event {i+1}\n")
                f.write("\n")

            else:
                start = cur_pos
                end = r.start

                cur_pos = r.end

                start += analysis_window if start > 0 else 0
                end -= analysis_window

                if end - start < args.min_silence_dur:
                    continue

                silence_segments.append((start, end))

                if args.file_to_fix is None:

                    # Write the start and end times of each event to the file
                    f.write(f"{region_id}\n")
                    f.write(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n")
                    f.write(f"Silence {region_id}\n")
                    f.write("\n")
                    
                    region_id += 1
    
    if args.file_to_fix is None:
        return # Early exit

    # Initialize for non-speech processing if argument is provided
    non_speech_srt_entries = []
    non_speech_file_counter = 1
    loaded_audio_for_ns = None

    if args.non_speech_dir:
        os.makedirs(args.non_speech_dir, exist_ok=True)
        try:
            loaded_audio_for_ns = auditok.load(args.input)
            print(f"Input audio {args.input} loaded for non-speech segment extraction.")
        except Exception as e:
            logging.error(f"Failed to load audio file {args.input} for non-speech extraction: {e}")
            # Potentially disable non-speech processing if audio can't be loaded
            loaded_audio_for_ns = None

    if args.subtract_only:
        print(f"Subtracting silence from {args.file_to_fix} and writing to {output_file} against {len(silence_segments)} silence segments")

        segments = parse_srt(args.file_to_fix)
        if not segments:
            print(f"No segments found or parsed in {args.file_to_fix}. Exiting.")
            return

        index = 0

        with open(output_file, "w") as f:
            for s in segments:
                start = s['start_time']
                end = s['end_time']
                print(f"Processing segment {s['index']} from {start:.2f} to {end:.2f}")

                while index < len(silence_segments) and silence_segments[index][1] < start:
                    print(f"Skipping silence segment {index} from {silence_segments[index][0]:.2f} to {silence_segments[index][1]:.2f} because end of silence {silence_segments[index][1]:.2f} < start of segment {start:.2f}")
                    index += 1

                if index < len(silence_segments):
                    silence_start, silence_end = silence_segments[index]
                    if silence_start < start and start < silence_end and silence_end < end:
                        print(f"Shortening segment from {start:.2f} to {end:.2f} by silence from {silence_segments[index][0]:.2f} to {silence_end:.2f}")
                        start = silence_end

                while index < len(silence_segments) and silence_segments[index][1] < end:
                    print(f"Skipping silence segment {index} from {silence_segments[index][0]:.2f} to {silence_segments[index][1]:.2f} because start of silence {silence_segments[index][0]:.2f} < end of segment {end:.2f}")
                    index += 1

                if index < len(silence_segments):
                    silence_start, silence_end = silence_segments[index]
                    if silence_start > start and end < silence_end and silence_start < end:
                        print(f"Shortening segment from {start} to {end} by silence from {silence_start:.2f} to {silence_segments[index][1]:.2f}")
                        end = silence_start
                
                # Write the start and end times of each event to the file
                f.write(f"{s['index']}\n")
                f.write(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n")
                f.write(f"{s['text']}\n")
                f.write("\n")

    else: # This is the new block for subtract_only=False

        segments = parse_srt(args.file_to_fix)
        if not segments:
             print(f"No segments found or parsed in {args.file_to_fix}. Exiting.")
             return
        
        print(f"Expanding/Subtracting segments in {args.file_to_fix} using {len(segments)} audio segments and writing to {output_file}")

        full_list = []
        for s in segments:
            full_list.append(
                {
                    'start': s['start_time'], 
                    'end': s['end_time'],
                    'text': s['text'],
                    'index': s['index'],
                    'kind': 'segment'
                })
        for s in silence_segments:
            full_list.append(
                {
                    'start': s[0], 
                    'end': s[1],
                    'kind': 'silence'
                })
        # Sort the full list by start time
        full_list.sort(key=lambda x: x['start'])

        # --- Write all adjusted segments to the output file ---
        print(f"\nWriting {len(segments)} segments to {output_file}")
        with open(output_file, "w") as f:
            
            last_speech_segment = None
            index = 0
            while index < len(full_list):

                # Get the current segment
                s = full_list[index]

                # Check if it's a silence segment
                if s['kind'] == 'segment':

                    last_speech_segment = s

                    if index - 1 >= 0 and full_list[index - 1]['kind'] == 'silence' and full_list[index - 1]['end'] < s['end']:
                        print(f"Moving start of segment {s['index']} from {s['start']:.3f} to {full_list[index - 1]['end']:.3f}")
                        s['start'] = full_list[index - 1]['end']

                    if index + 1 < len(full_list) and full_list[index + 1]['kind'] == 'silence':
                        s['end'] = full_list[index + 1]['start']

                    if s['start'] > s['end']:
                        raise ValueError(f"Invalid segment: {s['start']} > {s['end']}")

                    f.write(f"{s['index']}\n")
                    f.write(f"{seconds_to_srt_time(s['start'])} --> {seconds_to_srt_time(s['end'])}\n")
                    f.write(f"{s['text']}\n\n")

                elif s['kind'] == 'silence':

                    # If there are two silence segments in a row but no ASR segment in between, this indicates
                    # a potential non-verbal event (click, which might need to be removed)
                    if index + 1 < len(full_list) and full_list[index + 1]['kind'] == 'silence':
                        # This non-speech event is the audio between s['end'] and full_list[index+1]['start']
                        # The actual audio corresponds to an auditok event r where:
                        # r.start = s['end'] + analysis_window
                        # r.end = full_list[index+1]['start'] - analysis_window
                        
                        ns_start_time = s['end'] + analysis_window
                        ns_end_time = full_list[index+1]['start'] - analysis_window

                        if ns_end_time > ns_start_time: # Ensure positive duration
                            print(f"INFO: Non-ASR event detected between silence segments from {s['end']:.3f} (adj to {ns_start_time:.3f}) to {full_list[index + 1]['start']:.3f} (adj to {ns_end_time:.3f}).")

                            if args.non_speech_dir and loaded_audio_for_ns:
                                # Find previous ASR segment index
                                prev_asr_segment_obj = None
                                for i in range(index - 1, -1, -1):
                                    if full_list[i]['kind'] == 'segment':
                                        prev_asr_segment_obj = full_list[i]
                                        break
                                prev_asr_idx_text = str(prev_asr_segment_obj['index']) + " " + prev_asr_segment_obj['text'] if prev_asr_segment_obj else "start of audio"

                                # Find next ASR segment index
                                next_asr_segment_obj = None
                                for i in range(index + 2, len(full_list)):
                                    if full_list[i]['kind'] == 'segment':
                                        next_asr_segment_obj = full_list[i]
                                        break
                                next_asr_idx_text = str(next_asr_segment_obj['index']) + " " + next_asr_segment_obj['text'] if next_asr_segment_obj else "end of audio"
                                
                                ns_filename = f"{non_speech_file_counter:04d}.wav"
                                ns_filepath = os.path.join(args.non_speech_dir, ns_filename)
                                
                                try:
                                    # auditok slices audio in milliseconds
                                    segment_to_save = loaded_audio_for_ns[int(ns_start_time * 1000):int(ns_end_time * 1000)]
                                    segment_to_save.save(ns_filepath)
                                    
                                    srt_text = f"Non-speech segment detected between segment '{prev_asr_idx_text}' and segment '{next_asr_idx_text}'."
                                    non_speech_srt_entries.append({
                                        'index': non_speech_file_counter,
                                        'start_time': ns_start_time,
                                        'end_time': ns_end_time,
                                        'text': srt_text
                                    })
                                    print(f"Saved non-speech segment {ns_filename} and prepared SRT entry.")
                                    non_speech_file_counter += 1
                                except Exception as e:
                                    logging.error(f"Error saving non-speech segment {ns_filename}: {e}")
                        else:
                            print(f"WARN: Potential non-ASR event detected but duration is zero or negative ({ns_start_time=}, {ns_end_time=}). Skipping.")

                index += 1
    
    # After the loop, write the non_speech.srt file if entries exist
    if args.non_speech_dir and non_speech_srt_entries:
        ns_srt_path = os.path.join(args.non_speech_dir, "non-speech.srt")
        with open(ns_srt_path, "w", encoding='utf-8') as ns_f:
            for entry in non_speech_srt_entries:
                ns_f.write(f"{entry['index']}\n")
                ns_f.write(f"{seconds_to_srt_time(entry['start_time'])} --> {seconds_to_srt_time(entry['end_time'])}\n")
                ns_f.write(f"{entry['text']}\n\n")
        print(f"Non-speech SRT file written to {ns_srt_path}")

if __name__ == "__main__":

    # parser options
    parser = argparse.ArgumentParser(description="Silence SRT will adjust an input SRT file based on silence detected in a .wav file.")
    parser.add_argument(
        "-i", "--input", type=str, help="Input .wav file (just speech)", required=True)

    # File to fix
    parser.add_argument(
        '-f', "--file_to_fix", "--file", type=str, help="Input .srt file to fix. If not given outputs just the silence segments")
    
    parser.add_argument(
        "-o", "--output", default="output.srt", type=str, help="Output srt file")
    
    # 35 == needs very quite to detect  == less silence
    # 40 == needs some quite to detect  
    # 55 == some speech is lost         == more silence
    parser.add_argument(
        "-t", "--threshold", default=40, type=int, help="Detection threshold - energy-based. If energy exceeds this value, the event is considered valid.")
    
    parser.add_argument(
        "-m", "--min_dur", default=0.1, type=float, help="Minimum duration of a valid audio event in seconds")
    
    parser.add_argument(
        "-M", "--max_dur", default=24*60*60, type=float, help="Maximum duration of an event")
    
    parser.add_argument(
        "-s", "--min_silence_dur", default=0.05, type=float, help="Minimum duration of silence in seconds")
    
    parser.add_argument(
        "-n", "--negate", action="store_true", help="Report events, rather than silence")
    
    parser.add_argument(
        "--subtract_only", "--subtract-only", action="store_true", help="Only shorten the attached SRT file segments by the silence detected. Do not extend.")
    
    parser.add_argument(
        "--non-speech-dir", type=str, help="Directory to save non-speech audio segments and a non-speech.srt file.")

    args = parser.parse_args()

    if args.negate and args.file_to_fix is not None:
        parser.error("Cannot use --negate with --file_to_fix")

    main(args)
