import os
import shutil
from pytubefix  import YouTube
from dotenv import load_dotenv
import urllib.request
import subprocess
import telebot
from telebot import types

def youtube_initial_request(link,dir):

    yt = YouTube(link, use_oauth=True, allow_oauth_cache=True,client='WEB_CREATOR')
    print(link)
    vid_streams = {}
    for stream in yt.streams.filter(progressive=False,file_extension="mp4",only_video=True):
        vid_streams[stream.resolution] = [stream.itag, stream.filesize_mb]
    print(yt.thumbnail_url)
    try:
        urllib.request.urlretrieve(yt.thumbnail_url,f"{dir}/thumbnail.jpg")
    except urllib.error.HTTPError as e:
        print(e.reason)

    print(vid_streams)
    return yt.title,yt.author,vid_streams,yt.streams.get_by_itag(249).filesize_mb,yt.streams.get_by_itag(250).filesize_mb,\
           yt.streams.get_by_itag(251).filesize_mb

load_dotenv(".env")
bot = telebot.TeleBot(os.environ.get('API_KEY'))

@bot.message_handler(commands = ['start'])
def greeting(message):
    bot.send_message(message.from_user.id, "Hi! I'm a youtube downloader, send me a link and get the content you want")

@bot.message_handler(content_types='text')
def get_links(message):
    dir = message.text[24::].replace("?","")
    if not os.path.exists(dir): os.makedirs(dir)
    title,author,streams,audio_lowq_size, audio_medq_size, audio_highq_size = youtube_initial_request(message.text,dir)

    thumbnail = open(f"{dir}/thumbnail.jpg","rb")
    resolutions_label = ""
    resolutions = []
    res_map = {'2160p':audio_highq_size,'1440p':audio_highq_size,'1080p':audio_highq_size,
               '720p':audio_highq_size,'360p':audio_medq_size,'480p':audio_medq_size,'144p':audio_lowq_size,'240p':audio_lowq_size}

    for key in streams:
        audio_size = res_map[key]
        resolutions.append(key)
        resolutions_label += f"{key}: {round(streams[key][1] + audio_size ,1) }mb\n"
    print(resolutions)
    keyboard = [
                [types.InlineKeyboardButton(f'{resolutions[0] }', callback_data=f'vid {message.text} {streams[resolutions[0]][0]} {resolutions[0]}'),
                 types.InlineKeyboardButton(f'{resolutions[1] }', callback_data=f'vid {message.text} {streams[resolutions[1]][0]} {resolutions[1]}'),
                 types.InlineKeyboardButton(f'{resolutions[2] }', callback_data=f'vid {message.text} {streams[resolutions[2]][0]} {resolutions[2]}')],
                [types.InlineKeyboardButton(f'{resolutions[3]}', callback_data=f'vid {message.text} {streams[resolutions[3]][0]} {resolutions[3]}'),
                types.InlineKeyboardButton(f'{resolutions[4] }', callback_data=f'vid {message.text} {streams[resolutions[4]][0]} {resolutions[4]}'),
                types.InlineKeyboardButton(f'{resolutions[5] }', callback_data=f'vid {message.text} {streams[resolutions[5]][0]} {resolutions[5]}')],
                [types.InlineKeyboardButton(f'MP3', callback_data=f'MP3 {message.text}'),
                types.InlineKeyboardButton(f'Thumbnail', callback_data=f'Tmb {message.text}')],
                ]
    qMarkup = types.InlineKeyboardMarkup(keyboard,row_width = 3)
    bot.send_photo(chat_id= message.from_user.id, photo=thumbnail,
                   caption=f"{author}\n{title}\n{resolutions_label}MP3: {round(audio_highq_size,1)}mb",
                   reply_to_message_id=message.message_id,reply_markup=qMarkup)
    thumbnail.close()
    #bot.send_message(message.from_user.id,"Invalid Input")


@bot.callback_query_handler(func=lambda callback:callback.data)
def youtube(callback):
    if callback.data[:3] == "vid" :
        foo, link, video_itag, resolution = callback.data.split(" ")
        yt = YouTube(link)

        dir = link[24::].replace("?","")

        audio_itag = 251
        if resolution == '144p' or resolution == '240p': audio_itag = 249
        elif resolution == '360p' or resolution == '480p': audio_itag = 250
        elif resolution == '720p' or resolution == '1080p': audio_itag = 251


        video_stream = yt.streams.get_by_itag(video_itag)
        audio_stream = yt.streams.get_by_itag(audio_itag)

        video_file = f'{dir}/video.mp4'
        audio_file = f'{dir}/audio.webm'
        output_file = f'{dir}/combined_video.mp4'

        bot.send_message(chat_id = callback.from_user.id,text = "Downloading...")

        video_stream.download(f'{dir}',filename = "video.mp4")
        audio_stream.download(f'{dir}',filename = "audio.webm")

        command = [
            'ffmpeg',
            '-i', video_file,
            '-i', audio_file,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-strict', 'experimental',
            output_file
        ]

        subprocess.run(command, check=True)

        bot.send_message(chat_id = callback.from_user.id,text = "Sending...")

        video = open(output_file,'rb')
        bot.send_video(chat_id=callback.from_user.id,video=video,supports_streaming=True,caption=f'{yt.author}\n{yt.title}\n{video_stream.resolution}')
        video.close()


    elif callback.data[:3] == "MP3" :
        link = callback.data.split(" ")[-1]
        dir = link[24::].replace("?", "")

        yt = YouTube(link)
        audio_stream = yt.streams.get_by_itag(251)

        audio_file = f'{dir}/audio'
        audio_stream.download(filename=audio_file,mp3=True)

        audio = open(f'{audio_file}.mp3', 'rb')

        bot.send_audio(chat_id=callback.from_user.id, audio=audio, caption=f'{yt.author}\n{yt.title}\n Mp3')

        audio.close()

    elif callback.data[:3] == "Tmb":
        link = callback.data.split(" ")[-1]
        dir = link[24::].replace("?", "")

        yt = YouTube(link)
        thumbnail = open(f"{dir}/thumbnail.jpg", "rb")

        bot.send_photo(chat_id= callback.from_user.id, photo=thumbnail,
                       caption=f"{yt.title}\n{yt.author}")
        thumbnail.close()
    shutil.rmtree(dir)
bot.polling(none_stop=True, interval=0)
