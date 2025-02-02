import traceback
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
        self.soul_handler.ensure_mic_active()
        self.controller.player_name = message_info.nickname
        info = self.play_playlist(query)
        return info

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
            self.handler.logger.erryyor('Failed to find playlist tab')
            return {
                'error': 'Failed to find playlist tab',
            }
        result = self.handler.wait_for_element_clickable_plus('playlist_result')
        result.click()
        self.handler.logger.info("Selected playlist tab")

        play_button = self.handler.wait_for_element_clickable_plus('play_all', timeout=5)
        if play_button:
            self.handler.logger.info("Found play all button")
            play_button.click()
        else:
            play_button = self.handler.wait_for_element_clickable_plus('play_album')
            if play_button:
                self.handler.logger.info("Found play album button")
                play_button.click()
            else:
                self.handler.logger.error('Failed to find playlist button')
                return {'error': 'Failed to find play button'}
        return {
            'playlist': result.text,
        }
