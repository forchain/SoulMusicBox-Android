import traceback

from ..utils.playlist_parser import PlaylistParser
from ..core.base_command import BaseCommand

def create_command(controller):
    playlist_command = PlaylistCommand(controller)
    controller.playlist_command = playlist_command
    return playlist_command


command = None


class PlaylistCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    def process(self, message_info, parameters):
        query = ' '.join(parameters)

        if len(parameters) == 0:
            playing_info = self.handler.get_playlist_info()
        else:
            self.controller.player_name = message_info.nickname
            self.soul_handler.ensure_mic_active()
            playing_info = self.play_playlist(query)

        return playing_info

    def select_playlist_tab(self):
        tab = self.handler.wait_for_element_clickable_plus('playlist_tab')
        if not tab:
            self.handler.logger.error("Cannot find playlist tab")
            return False

        tab.click()
        self.handler.logger.info("Selected playlist tab")
        return True

    def play_playlist(self, query: str):
        if not self.handler.query_music(query):
            self.handler.logger.error('Failed to query music in playlist')
            return {
                'error': 'Failed to query music playlist',
            }

        if not self.select_playlist_tab():
            self.handler.logger.error('Failed to find playlist tab')
            return {
                'error': 'Failed to find playlist tab',
            }
        self.handler.logger.info("Selected playlist tab")

        result = self.handler.wait_for_element_clickable_plus('playlist_result')
        result.click()
        self.handler.logger.info("Selected playlist result")

        playlist = result.text
        parser = PlaylistParser()
        
        subject, topic = parser.parse_playlist_name(playlist)
        if not subject:
            self.handler.logger.warning('Failed to parse playlist name')
            singer_name = self.handler.try_find_element_plus('singer_name')
            if singer_name:
                subject = singer_name.text
                
        if not topic:
            self.handler.logger.warning('Failed to parse playlist topic')
            song_name = self.handler.try_find_element_plus('song_name')
            if song_name:
                topic = song_name.text

        play_button = self.handler.wait_for_element_clickable_plus('play_all', timeout=5)
        if play_button:
            self.handler.logger.info("Found play all button")
            play_button.click()

            playing_info = self.handler.get_playlist_info()
            if not 'error' in playing_info:
                playlist = f'Playing {playlist}\n\n{playing_info["playlist"]}'

            self.controller.title_command.change_title(subject)
            self.controller.topic_command.change_topic(topic)
        else:
            play_button = self.handler.wait_for_element_clickable_plus('play_album')
            if play_button:
                self.handler.logger.info("Found play album button")
                play_button.click()

                playing_info = self.handler.get_playlist_info() 
                if not 'error' in playing_info:
                    playlist = f'Playing {playlist}\n\n{playing_info["playlist"]}'

                playlist_screen = self.handler.wait_for_element_clickable_plus('playlist_screen')
                if playlist_screen:
                    self.handler.logger.info("Found playlist screen")
                    self.handler.press_back()

                self.controller.title_command.change_title(subject)
                self.controller.topic_command.change_topic(topic)
            else:
                self.handler.logger.error('Failed to find playlist button')
                return {'error': 'Failed to find play button'}
        self.handler.list_mode = 'playlist'
        return {
            'playlist': playlist,
        }
