
### Berömdrömmen
### Author: Micke Kring
### Contact: mikael.kring@ri.se

# Python imports
import os
import hmac
from os import environ
from datetime import datetime
from sys import platform
import hashlib
from concurrent.futures import ThreadPoolExecutor

# External imports
import streamlit as st
from audiorecorder import audiorecorder
from openai import OpenAI

# Local imports
from transcribe import transcribe_with_whisper_openai
from llm import process_text, process_text_openai
from voice import text_to_speech
import prompts as p
from mix_audio import mix_music_and_voice
import config as c
from styling import page_configuration, page_styling
from split_audio import split_audio_to_chunks


### INITIAL VARIABLES

# Creates folder if they don't exist
os.makedirs("audio", exist_ok=True) # Where audio/video files are stored for transcription
os.makedirs("text", exist_ok=True) # Where transcribed document are beeing stored


### PASSWORD

if c.run_mode != "local":
    def check_password():
        """Returns `True` if the user had the correct password."""

        def password_entered():
            """Checks whether a password entered by the user is correct."""
            if hmac.compare_digest(st.session_state["password"], st.secrets["password"]):
                st.session_state["password_correct"] = True
                del st.session_state["password"]  # Don't store the password.
            else:
                st.session_state["password_correct"] = False

        # Return True if the password is validated.
        if st.session_state.get("password_correct", False):
            return True

        # Show input for password.
        st.text_input(
            "Lösenord", type="password", on_change=password_entered, key="password"
        )
        if "password_correct" in st.session_state:
            st.error("😕 Oj, fel lösenord. Prova igen.")
        return False


    if not check_password():
        st.stop()  # Do not continue if check_password is not True.


# Check and set default values if not set in session_state
# of Streamlit

if "spoken_language" not in st.session_state: # What language source audio is in
    st.session_state["spoken_language"] = "Automatiskt"
if "file_name_converted" not in st.session_state: # Audio file name
    st.session_state["file_name_converted"] = None
if "gpt_template" not in st.session_state: # Audio file name
    st.session_state["gpt_template"] = "Ljus röst - Glad, positiv och svär gärna"
if "llm_temperature" not in st.session_state:
    st.session_state["llm_temperature"] = c.llm_temp
if "llm_chat_model" not in st.session_state:
    st.session_state["llm_chat_model"] = c.llm_model
if "audio_file" not in st.session_state:
    st.session_state["audio_file"] = False


# Checking if uploaded or recorded audio file has been transcribed
def compute_file_hash(uploaded_file):

    print("\nSTART: Check if audio file has been transcribed - hash")

    # Compute the MD5 hash of a file
    hasher = hashlib.md5()
    
    for chunk in iter(lambda: uploaded_file.read(4096), b""):
        hasher.update(chunk)
    uploaded_file.seek(0)  # Reset the file pointer to the beginning

    print("DONE: Check if audio file has been transcribed - hash")
    
    return hasher.hexdigest()



### MAIN APP ###########################

page_configuration()
page_styling()


def main():

    global translation
    global model_map_transcribe_model


    ### SIDEBAR

    st.sidebar.markdown(
        "#"
        )


    ### ### ### ### ### ### ### ### ### ### ###
    ### MAIN PAGE
    
    topcol1, topcol2 = st.columns([2, 2], gap="large")

    with topcol1:
        # Title
        st.markdown(f"""## :material/thumb_up: {c.app_name}""")
        st.markdown("""Tryck på knappen __Spela in__ här under och ge ditt beröm till din kollega. När du är 
            klar trycker du på __Stoppa__. Vänta tills ditt tal gjorts om till text och 
            välj sedan en mall för beröm.""")

        
    with topcol2:

        with st.expander(":material/help: Vill du ha tips?"):
            st.markdown("""__Att ge beröm till en kollega kan kännas lite pinsamt, men forskning har visat att 
det kan få oss att må bättre på jobbet och att vi till och med blir mer produktiva. 
Att få höra att kollegor värdesätter och uppmärksammar en ökar ens välmående helt enkelt.__

Det viktigaste är att det kommer från hjärtat och ett spontant beröm kommer du långt med.
Men om du vill ha några tips, så försök att vara specifik. Berätta vad det är du tycker din 
kollega gör så bra och hur det får dig att känna. I stället för att bara säga ‘bra jobbat’, 
nämn något konkret, som ‘jag uppskattar verkligen att du kan hålla lugnet under press.’ 

Du kan också ge beröm både för prestationer och egenskaper. Du kan berömma hur någon löser 
ett problem, men även deras samarbetsförmåga, empati eller hur de stöttar andra i teamet.

Kom ihåg att även vara jämställd i hur du ger beröm. Se till att alla får erkännande för 
sina insatser, oavsett kön, titel eller bakgrund. Det hjälper till att skapa ett mer 
inkluderande arbetsklimat.

Och till sist, var ärlig. Människor känner av när beröm är genuint. Så när du ser något bra – säg det!
Att regelbundet ge beröm bygger upp tillit, respekt och en arbetsplats där alla känner sig 
sedda och uppskattade.
""")


    maincol1, maincol2 = st.columns([2, 2], gap="large")


    with maincol1:

        st.markdown("#### Beröm din kollega")

        # Creates the audio recorder
        audio = audiorecorder(start_prompt="Spela in", stop_prompt="Stoppa", pause_prompt="", key=None)

        # The rest of the code in tab2 works the same way as in tab1, so it's not going to be
        # commented.
        if len(audio) > 0:

            # To save audio to a file, use pydub export method
            audio.export("audio/local_recording.wav", format="wav")

            # Open the saved audio file and compute its hash
            with open("audio/local_recording.wav", 'rb') as file:
                current_file_hash = compute_file_hash(file)

            # If the uploaded file hash is different from the one in session state, reset the state
            if "file_hash" not in st.session_state or st.session_state.file_hash != current_file_hash:
                st.session_state.file_hash = current_file_hash
                
                if "transcribed" in st.session_state:
                    del st.session_state.transcribed

            if "transcribed" not in st.session_state:

                with st.status('Delar upp ljudfilen i mindre bitar...'):
                    chunk_paths = split_audio_to_chunks("audio/local_recording.wav")

                # Transcribe chunks in parallel
                with st.status('Transkriberar alla ljudbitar. Det här kan ta ett tag beroende på lång inspelningen är...'):
                    with ThreadPoolExecutor() as executor:
                        # Open each chunk as a file object and pass it to transcribe_with_whisper_openai
                        transcriptions = list(executor.map(
                            lambda chunk: transcribe_with_whisper_openai(open(chunk, "rb"), os.path.basename(chunk)), 
                            chunk_paths
                        )) 
                        # Combine all the transcriptions into one
                        st.session_state.transcribed = "\n".join(transcriptions)
            
            st.markdown("#### Ditt beröm")
            st.write(st.session_state.transcribed)



    with maincol2:

        st.markdown("#### Skapa AI-beröm")

        if "transcribed" in st.session_state:

            system_prompt = ""

            gpt_template = st.selectbox(
                "Välj mall", 
                ["Välj mall", 
                 "Ljus röst - Glad, positiv och svär gärna",
                 "Ljus röst - Korrekt myndighetsperson",
                 "Djup röst - Fåordig men glad och rolig",
                 "Djup röst - Skojfrisk och svärande"

                 ],
                index=[
                 "Ljus röst - Glad, positiv och svär gärna",
                 "Ljus röst - Korrekt myndighetsperson",
                 "Djup röst - Fåordig men glad och rolig",
                 "Djup röst - Skojfrisk och svärande"
                ].index(st.session_state["gpt_template"]),
            )

            if gpt_template == "Ljus röst - Glad, positiv och svär gärna":
                system_prompt = p.ljus_rost_1
            
            elif gpt_template == "Ljus röst - Korrekt myndighetsperson":
                system_prompt = p.ljus_rost_2
            
            elif gpt_template == "Djup röst - Fåordig men glad och rolig":
                system_prompt = p.djup_rost_1

            elif gpt_template == "Djup röst - Skojfrisk och svärande":
                system_prompt = p.djup_rost_2


            with st.popover("Visa prompt"):
                st.write(system_prompt)


            if gpt_template != "Välj mall":
                
                llm_model = st.session_state["llm_chat_model"]
                llm_temp = st.session_state["llm_temperature"]
                
                if "llama" in llm_model:
                    full_response = process_text(llm_model, llm_temp, system_prompt, st.session_state.transcribed)
                else:
                    full_response = process_text_openai(llm_model, llm_temp, system_prompt, st.session_state.transcribed)
                
                if gpt_template == "Ljus röst - Glad, positiv och svär gärna": # Sanna uppåt

                    voice = "4xkUqaR9MYOJHoaC1Nak"
                    stability = 0.3
                    similarity_boost = 0.86
                    
                    with st.spinner(text="Läser in din text..."):
                        tts_audio = text_to_speech(full_response, voice, stability, similarity_boost)

                    with st.spinner(text="Mixar musik och röst..."):
                            mix_music_and_voice("low")
                            st.audio("mixed_audio.mp3", format="audio/mpeg", loop=False)
                
                elif gpt_template == "Ljus röst - Korrekt myndighetsperson": # Sanna

                    voice = "aSLKtNoVBZlxQEMsnGL2"
                    stability = 0.5
                    similarity_boost = 0.75
                    
                    with st.spinner(text="Läser in din text..."):
                        tts_audio = text_to_speech(full_response, voice, stability, similarity_boost)

                    with st.spinner(text="Mixar musik och röst..."):
                            mix_music_and_voice("low")
                            st.audio("mixed_audio.mp3", format="audio/mpeg", loop=False)

                elif gpt_template == "Djup röst - Fåordig men glad och rolig": # Jonas

                    voice = "e6OiUVixGLmvtdn2GJYE"
                    stability = 0.71
                    similarity_boost = 0.48
                    
                    with st.spinner(text="Läser in din text..."):
                        tts_audio = text_to_speech(full_response, voice, stability, similarity_boost)

                    with st.spinner(text="Mixar musik och röst..."):
                            mix_music_and_voice("high")
                            st.audio("mixed_audio.mp3", format="audio/mpeg", loop=False)

                elif gpt_template == "Djup röst - Skojfrisk och svärande": # Dave

                    voice = "m8oYKlEB8ecBLgKRMcwy"
                    stability = 0.5
                    similarity_boost = 0.6
                    
                    with st.spinner(text="Läser in din text..."):
                        tts_audio = text_to_speech(full_response, voice, stability, similarity_boost)

                    with st.spinner(text="Mixar musik och röst..."):
                            mix_music_and_voice("medium")
                            st.audio("mixed_audio.mp3", format="audio/mpeg", loop=False)
                
                else:
                    pass
                

if __name__ == "__main__":
    main()



