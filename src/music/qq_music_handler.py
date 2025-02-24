from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from selenium.common import StaleElementReferenceException

from ..utils.app_handler import AppHandler
from ..utils.lyrics_formatter import LyricsFormatter
import time
import re
import pytesseract
from PIL import Image
import io
import base64
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
import traceback
import jieba
from langdetect import detect_langs
import langdetect

# 在导入后设置种子
langdetect.DetectorFactory.seed = 0  # 使用赋值而不是调用


class QQMusicHandler(AppHandler):
    def __init__(self, driver, config, controller):
        super().__init__(driver, config, controller)

        self.lyrics_formatter = None  # Will be set by app_controller
        self.ktv_mode = False  # KTV mode state
        self.last_lyrics = ""  # Store last recognized lyrics
        self.last_lyrics_lines = []
        self.no_skip = 0
        self.list_mode = 'unknown'

        # Optimize driver settings
        self.driver.update_settings({
            "waitForIdleTimeout": 0,  # Don't wait for idle state
            "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
            "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
        })

    def hide_player(self):
        self.press_back()
        self.logger.info("Hide player panel")
        time.sleep(1)

    def navigate_to_home(self):
        """Navigate back to home page"""
        # Keep clicking back until no more back buttons found
        n = 0
        while n < 9:
            search_entry = self.try_find_element_plus('search_entry')
            if search_entry:
                go_back = self.try_find_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.logger.info(f"Clicked go back button")
                else:
                    self.logger.info(f"Found search entry, assume we're at home page")
                    return True
            else:
                self.press_back()
                n += 1
        return False

    def get_playing_info(self):
        """Get current playing song and singer info"""
        song_element = self.try_find_element_plus("song_name")
        if not song_element:
            return {
                "song": "Unknown",
                "singer": "Unknown",
                "album": "Unknown",
            }
        song = song_element.text
        singer_element = self.try_find_element_plus("singer_name")
        if not song_element:
            return {
                "song": song,
                "singer": "Unknown",
                "album": "Unknown",
            }
        singer_album = singer_element.text.split('·')
        singer = singer_album[0]
        album = singer_album[1] if singer_album[1] else "Unknown"

        return {
            'song': song,
            'singer': singer,
            'album': album
        }

    def get_current_playing(self):
        """Get current playing song and singer info"""
        try:
            song_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['current_song']
            )
            singer_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['current_singer']
            )
            return {
                'song': song_element.text,
                'singer': singer_element.text
            }
        except Exception as e:
            print(f"Error getting current playing info: {str(e)}")
            return None

    def query_music(self, music_query: str):
        """Common logic for preparing music playback"""
        if not self.switch_to_app():
            self.logger.info(f"Failed to switched to QQ Music app")
            return False
        self.logger.info(f"Switched to QQ Music app")

        search_box = self.try_find_element_plus('search_box', log=False)
        if not search_box:
            go_back = self.try_find_element_plus('go_back', log=False)
            if go_back:
                self.logger.info(f"Clicked Go Back button")
                go_back.click()
            else:
                self.press_back()

        go_home = False
        playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        search_box = None
        if playlist_entry:
            search_box = self.try_find_element_plus('search_box', log=False)
            if not search_box:
                go_home = True
        else:
            go_home = True

        if go_home:
            # Go back to home page
            self.navigate_to_home()
            self.logger.info(f"Navigated to home page")

            # Find search entry
            search_entry = self.wait_for_element_clickable_plus('search_entry')
            if search_entry:
                search_entry.click()
                self.logger.info(f"Clicked search entry")
            else:
                self.logger.error(f"failed to find search entry")
                return False

            # Find and click search box
            search_box = self.wait_for_element_clickable_plus('search_box')

        if search_box:
            clear_search = self.try_find_element_plus('clear_search', log=False)
            if clear_search:
                clear_search.click()
                self.logger.info(f"Clear search")
            search_box.click()
        else:
            self.logger.error(f"Cannot find search entry")
            return False

        # Use clipboard operations from parent class
        self.set_clipboard_text(music_query)
        self.paste_text()
        return True

    def _prepare_music_playback(self, music_query):
        if not self.query_music(music_query):
            self.logger.error(f"Failed to query music query: {music_query}")
            playing_info = {
                'error': f"Failed to query music: {music_query}"
            }
            return playing_info

        self.select_song_tab()

        playing_info = self.get_playing_info()
        if not playing_info:
            self.logger.warning(f"No playing info found for query: {music_query}")
            playing_info = {
                'error': f"No playing info found for query: {music_query}"
            }
            return playing_info

        self.logger.info(f"Found playing info: {playing_info}")

        if self.list_mode == 'singer':
            if playing_info['song'].endswith('(Live)') or (
                    playing_info['singer'] and playing_info['singer'] == playing_info['album']):
                self.no_skip += 1

        studio_version = self.try_find_element_plus('studio_version', log=False)
        if studio_version:
            studio_version.click()
            self.logger.info("Alter to studio version")

        return playing_info

    def select_song_tab(self):
        """Select the 'Songs' tab in search results"""
        song_tab = self.wait_for_element_clickable(
            AppiumBy.XPATH,
            self.config['elements']['song_tab']
        )
        song_tab.click()
        self.logger.info("Selected songs tab")

    def select_lyrics_tab(self):
        self.press_right_key()
        self.press_right_key()

        """Select the 'lyrics' tab in search results"""
        lyrics_tab = self.wait_for_element_clickable(
            AppiumBy.XPATH,
            self.config['elements']['lyrics_tab']
        )
        if not lyrics_tab:
            print("Cannot find lyrics tab")
            return False

        lyrics_tab.click()
        print("Selected lyrics tab")
        return True

    def play_singer(self, query: str):

        if not self.query_music(query):
            return {
                'error': 'Failed to query music playlist',
            }

        self.select_singer_tab()

        singer_result = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['singer_result'])
        if not singer_result:
            return {
                'error': 'Failed to find singer result',
            }

        singer_text = self.find_child_element(singer_result, AppiumBy.ID, self.config['elements']['singer_text'])
        singer_text.click()
        print("Selected singer result")

        self.wait_for_element(
            AppiumBy.ID, self.config['elements']['singer_tabs'])

        play_button = self.try_find_element(
            AppiumBy.ID, self.config['elements']['play_singer']
        )
        if not play_button:
            song_tab = self.try_find_element(
                AppiumBy.XPATH, self.config['elements']['song_tab'])
            if not song_tab:
                self.logger.error("Cannot find singer song tab")
                return {
                    'error': 'Failed to find singer song tab',
                }
            song_tab.click()
            self.logger.info("Selected singer tab")

            play_button = self.wait_for_element_clickable(
                AppiumBy.ID, self.config['elements']['play_singer']
            )

        if not play_button:
            self.logger.error(f"Cannot find play singer button")
            return {'error': 'Failed to find play button'}

        play_button.click()
        self.logger.info("Clicked play singer result")

        return {
            'singer': singer_text.text,
        }

    def play_playlist(self, query: str):

        if not self.query_music(query):
            return {
                'error': 'Failed to query music playlist',
            }

        if not self.select_playlist_tab():
            return {
                'error': 'Failed to find playlist tab',
            }
        result = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['playlist_result']
        )
        result.click()

        play_button = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['play_playlist']
        )
        if play_button:
            play_button.click()
        else:
            play_button = self.wait_for_element_clickable(
                AppiumBy.ID, self.config['elements']['playlist_item']
            )
            if play_button:
                play_button.click()
            else:
                return {'error': 'Failed to find play button'}

        return {
            'playlist': result.text,
        }

    def play_music(self, music_query):
        """Search and play music"""
        if music_query == '':
            playing_info = self.play_favorites()
            return playing_info

        playing_info = self._prepare_music_playback(music_query)
        if 'error' in playing_info:
            self.logger.error(f'Failed to play music {music_query}')
            return playing_info

        song_element = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['song_name']
        )
        song_element.click()
        self.logger.info(f"Select first song")

        return playing_info

    def play_next(self, music_query):
        """Search and play next music"""
        try:
            playing_info = self._prepare_music_playback(music_query)
            if 'error' in playing_info:
                self.logger.error(f'Failed to add music {music_query} to playlist')
                return playing_info

            # Click next button
            next_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['next_button']
            )
            next_button.click()
            self.logger.info(f"Clicked next button")

            return playing_info

        except Exception as e:
            print(f"Error playing next music: {str(e)}")
            return {
                'song': music_query,
                'singer': 'unknown'
            }

    def skip_song(self):
        """Skip to next song"""
        try:
            # Get current info before skip
            current_info = self.get_playback_info()

            # Execute shell command to simulate media button press
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_NEXT'
                }
            )
            self.logger.info(f"Skipped {current_info['song']} by {current_info['singer']}")

            # Return song info
            return {
                'song': current_info.get('song', 'Unknown'),
                'singer': current_info.get('singer', 'Unknown')
            }

        except Exception as e:
            self.logger.error(f"Error skipping song: {traceback.format_exc()}")
            return {
                'song': 'Unknown',
                'singer': 'Unknown'
            }

    def get_volume_level(self):
        """Get current volume level"""
        try:
            # Execute shell command to get volume
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys audio'
                }
            )

            # Parse volume level
            if result:
                # Split by "- STREAM_MUSIC:" first
                parts = result.split('- STREAM_MUSIC:')
                if len(parts) > 1:
                    # Find first streamVolume in second part
                    match = re.search(r'streamVolume:(\d+)', parts[1])
                    if match:
                        volume = int(match.group(1))
                        print(f"Current volume: {volume}")
                        return volume
            return 0
        except Exception as e:
            print(f"Error getting volume level: {str(e)}")
            traceback.print_exc()
            return 0

    def adjust_volume(self, delta=None):
        """
        Adjust volume level
        Args:
            delta: int, positive to increase, negative to decrease, None to just get current level
        Returns:
            dict: Result with level and times if adjusted, or error
        """
        try:
            vol = self.get_volume_level()
            if delta is None:
                # Just get current volume
                return {'volume': vol}

            # Adjust volume
            if delta < 0:
                times = abs(delta) if vol + delta > 0 else vol
                for i in range(times):
                    self.press_volume_down()
                    self.logger.info(f"Decreased volume ({i + 1}/{times})")
            else:
                if vol > delta:
                    times = vol - delta
                    for i in range(times):
                        self.press_volume_down()
                        self.logger.info(f"Decreased volume ({i + 1}/{times})")
                else:
                    times = delta - vol
                    for i in range(times):
                        self.press_volume_up()
                        self.logger.info(f"Increased volume ({i + 1}/{times})")

            # Get final volume level
            vol = self.get_volume_level()
            self.logger.info(f"Adjusted volume to {vol}")
            return {
                'volume': vol,
            }
        except Exception as e:
            print(f"Error adjusting volume: {traceback.format_exc()}")
            return {'error': f'Failed to adjust volume to {delta}'}

    def get_lyrics(self):
        """Get lyrics of current playing song"""
        try:
            if not self.switch_to_app():
                return {'error': 'Failed to switch to QQ Music app'}
            print("Switched to QQ Music app")

            # Switch to lyrics page
            error = self.switch_to_lyrics_page()
            if error:  # If result is not None, it means error
                return error

            # Find and click lyrics tool button
            lyrics_tool = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['lyrics_tool']
            )
            if not lyrics_tool:
                return {'error': 'Cannot find lyrics tool'}

            # Check if lyrics are available
            no_lyrics = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['no_lyrics']
            )
            if no_lyrics:
                return {'error': 'No lyrics available for this song'}

            lyrics_tool.click()
            print("Clicked lyrics tool")

            # Find and click lyrics poster button
            lyrics_poster = self.wait_for_element(
                AppiumBy.XPATH,
                self.config['elements']['lyrics_poster']
            )
            if not lyrics_poster:
                return {'error': 'Cannot find lyrics poster option'}
            if not lyrics_poster.is_enabled():
                return {'error': 'Lyrics poster disabled'}

            lyrics_poster.click()
            print("Clicked lyrics poster")
            self.wait_for_element(
                AppiumBy.ID,
                self.config['elements']['lyrics_line']
            )

            screen_size = self.driver.get_window_size()
            # Quick swipe to top of lyrics
            self.driver.swipe(
                screen_size['width'] // 2,  # Start from middle x
                screen_size['height'] * 0.3,  # Start from bottom part
                screen_size['width'] // 2,  # End at same x
                screen_size['height'] * 0.9,  # End at top
                100  # Fast swipe (300ms)
            )
            print("Quick swipe to top of lyrics")
            time.sleep(0.5)  # Wait for scroll to settle

            # Collect lyrics
            all_lyrics = []  # Use list to maintain order
            total_chars = 0
            screen_height = screen_size['height']
            previous_lines = []  # Store previous batch of lyrics

            while True:
                try:
                    # Find all lyrics lines
                    lyrics_lines = self.wait_for_element(
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )
                    if not lyrics_lines:
                        print(f'No lyrics lines found')
                        break

                    # Get fresh elements each time
                    lyrics_lines = self.driver.find_elements(
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )

                    # Get current batch of lyrics, handle StaleElementReferenceException
                    current_lines = []
                    for line in lyrics_lines:
                        try:
                            text = line.text.strip()
                            if text:
                                current_lines.append(text)
                        except:
                            continue

                    if not current_lines:
                        print("No valid lyrics in current view")
                        break

                    # Process new lyrics, handling overlapping
                    if previous_lines:
                        # Find overlap between previous end and current start
                        overlap_size = 0
                        for i in range(min(len(previous_lines), len(current_lines))):
                            if previous_lines[-i - 1:] == current_lines[:i + 1]:
                                overlap_size = i + 1

                        # Add only non-overlapping lines
                        new_lines = current_lines[overlap_size:]
                    else:
                        new_lines = current_lines

                    # Add new lines while checking character limit
                    too_long = False
                    for line in new_lines:
                        if total_chars + len(line) > 400:
                            print("Would exceed character limit, stopping")
                            too_long = True
                            break
                        all_lyrics.append(line)
                        total_chars += len(line)
                    if too_long:
                        break

                    # Check for end marker
                    end_marker = self.try_find_element(
                        AppiumBy.XPATH,
                        self.config['elements']['lyrics_end'],
                        log=False
                    )
                    if end_marker:
                        print("Reached lyrics end")
                        break

                    # Store current lines for next iteration
                    previous_lines = current_lines

                    # Scroll up half screen
                    self.driver.swipe(
                        screen_size['width'] // 2,
                        screen_height * 0.7,
                        screen_size['width'] // 2,
                        screen_height * 0.3,
                        400
                    )

                except Exception as e:
                    print(f"Error in lyrics collection loop: {str(e)}")
                    break

            # Join lyrics with newlines
            final_lyrics = '\n'.join(all_lyrics)
            print(f"Collected {len(all_lyrics)} lines of lyrics")

            # Press back to return
            self.press_back()

            return {'lyrics': final_lyrics if final_lyrics else "No lyrics available"}

        except Exception as e:
            self.logger.error(f"Error getting lyrics: {traceback.format_exc()}")
            return {'error': 'Failed to get lyrics'}

    def set_lyrics_formatter(self, formatter):
        self.lyrics_formatter = formatter

    def query_lyrics(self, query, group_num=0):
        if query == "":
            info = self.get_playback_info()
            if not info:
                self.logger.error(f"Failed to get playback info with query {query}")
                return {'error': f'Failed to get playback info'}
            query = f'{info["song"]} {info["singer"]} {info["album"]}'
        if not self.query_music(query):
            self.logger.error(f"Failed to query music with query {query}")
            return {
                'error': 'Failed to query lyrics',
            }
        if not self.select_lyrics_tab():
            self.logger.error(f"Failed to select lyrics tab with query {query}")
            return {
                'error': 'Failed to select lyrics tab',
            }
        lyrics = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['lyrics_text'])
        if not lyrics:
            self.logger.error(f"Failed to find lyrics lines with query {query}")
            return {'error': 'Failed to find lyrics lines'}
        lyrics.click()
        groups = self.process_lyrics(lyrics.text, 15, group_num)

        return {
            'groups': groups
        }

    def get_element_screenshot(self, element):
        """Get screenshot of specific element and perform OCR
        Args:
            element: WebElement to capture
        Returns:
            str: Recognized text
        """
        try:
            # Get element screenshot
            start_time = time.time()  # Start time for screenshot
            screenshot = element.screenshot_as_base64
            end_time = time.time()  # End time for screenshot
            print(f"Time taken to get screenshot: {end_time - start_time:.2f} seconds")
            image_data = base64.b64decode(screenshot)
            image = Image.open(io.BytesIO(image_data))

            # # Get image size
            # width, height = image.size
            #
            # # Define crop region (top 80 pixels)
            # crop_box = (0, 500, width, 800)  # (left, top, right, bottom)
            # cropped_image = image.crop(crop_box)

            # Perform OCR with Chinese support
            start_time = time.time()  # Start time for OCR
            text = pytesseract.image_to_string(
                image,
                lang='chi_sim+eng',  # Use both Chinese and English
                config='--psm 6'  # Assume uniform text block
            )
            end_time = time.time()  # End time for OCR
            print(f"Time taken for OCR: {end_time - start_time:.2f} seconds")

            return text.strip()
        except Exception as e:
            print(f"Error performing OCR: {str(e)}")
            return ""

    def start_ktv_mode(self, max_switches=9, switch_interval=1):
        """Start KTV mode to sync lyrics"""
        try:
            self.switch_to_app()
            print("Switched to QQ Music app")

            # Try to find live lyrics element
            live_lyrics = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['live_lyrics']
            )

            if not live_lyrics:
                # Try to activate player panel
                playing_bar = self.try_find_element(
                    AppiumBy.ID,
                    self.config['elements']['playing_bar']
                )
                if playing_bar:
                    playing_bar.click()
                    self.logger.info("Clicked playing bar")
                    time.sleep(1)
                    live_lyrics = self.try_find_element(
                        AppiumBy.ID,
                        self.config['elements']['live_lyrics']
                    )

            if not live_lyrics:
                yield "Live lyrics not available"
                return

            previous_lyrics = ""
            switches = 0

            while switches < max_switches:
                # Get lyrics using OCR
                current_lyrics = self.get_element_screenshot(live_lyrics)

                # Only yield if lyrics changed and not empty
                if current_lyrics and current_lyrics != previous_lyrics:
                    previous_lyrics = current_lyrics
                    yield current_lyrics

                time.sleep(switch_interval)
                switches += 1

                # Try to find live lyrics again
                live_lyrics = self.try_find_element(
                    AppiumBy.ID,
                    self.config['elements']['live_lyrics']
                )
                if not live_lyrics:
                    break

        except Exception as e:
            print(f"Error in KTV mode: {str(e)}")
            yield "Error getting live lyrics"

    def get_full_lyrics(self):
        """Get full lyrics by scrolling and combining all parts"""
        try:
            # First find lyrics container
            lyrics_container = self.wait_for_element(
                AppiumBy.XPATH,
                self.config['elements']['full_lyrics']
            )

            if not lyrics_container:
                return "No lyrics container found"

            # Print lyrics container info
            print(f"Lyrics container found: {lyrics_container}")
            print(f"Container size: {lyrics_container.size}")
            print(f"Container location: {lyrics_container.location}")
            print(f"Container tag name: {lyrics_container.tag_name}")
            print(f"Container text: {lyrics_container.text}")
            print(f"Container element id: {lyrics_container.id}")

            # Get initial lyrics elements
            lyrics_elements = lyrics_container.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            if not lyrics_elements:
                return "No lyrics elements found"

            # Collect initial lyrics
            lyrics_list = []
            seen_ids = set()
            last_element_id = None

            for element in lyrics_elements:
                text = element.text
                if text:
                    element_id = element.id
                    seen_ids.add(element_id)
                    lyrics_list.append(text)
                    last_element_id = element_id

            print(f"Collected {len(lyrics_list)} initial lyrics")
            print(f"Last element id: {last_element_id}")

            # Scroll to bottom to reveal more lyrics
            self.scroll_element(lyrics_container)
            print("Scrolled lyrics container to bottom")
            time.sleep(1)  # Wait for scroll animation

            # Get additional lyrics elements after scroll
            lyrics_elements = lyrics_container.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            found_last_element = False

            count = 0
            for element in lyrics_elements:
                element_id = element.id
                # Skip until we find the last element from previous section
                if not found_last_element:
                    if element_id == last_element_id:
                        found_last_element = True
                    continue

                # Add new lyrics that we haven't seen before
                if element_id not in seen_ids:
                    text = element.text
                    if text:
                        count += len(text)
                        if count + len(text) > 500:
                            break
                        seen_ids.add(element_id)
                        lyrics_list.append(text)

            print(f"Collected total {len(lyrics_list)} lyrics after scroll")

            # Join all lyrics
            full_lyrics = '\n'.join(lyrics_list)
            print("Combined all lyrics")
            return full_lyrics

        except Exception as e:
            print(f"Error getting full lyrics: {str(e)}")
            return "Error getting full lyrics"

    def scroll_element(self, element, start_y_percent=0.75, end_y_percent=0.25):
        """Scroll element using W3C Actions API
        Args:
            element: WebElement to scroll
            start_y_percent: Start y position as percentage of element height (0.75 = 75% from top)
            end_y_percent: End y position as percentage of element height (0.25 = 25% from top)
        """
        try:
            # Get element location and size
            size = element.size
            location = element.location

            # Calculate scroll coordinates
            start_x = location['x'] + size['width'] // 2
            start_y = location['y'] + int(size['height'] * start_y_percent)
            end_y = location['y'] + int(size['height'] * end_y_percent)

            # Create pointer input
            actions = ActionChains(self.driver)
            pointer = PointerInput(interaction.POINTER_TOUCH, "touch")

            # Create action sequence
            actions.w3c_actions = ActionBuilder(self.driver, mouse=pointer)
            actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
            actions.w3c_actions.pointer_action.pointer_down()
            # actions.w3c_actions.pointer_action.pause(0.01)
            actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
            actions.w3c_actions.pointer_action.release()

            # Perform action
            actions.perform()
            print(f"Scrolled element from {start_y} to {end_y}")
            time.sleep(1)  # Wait for scroll animation

        except Exception as e:
            print(f"Error scrolling element: {str(e)}")

    def get_playback_info(self):
        """Get current playback information including song info and state"""
        # Get media session info
        result = self.driver.execute_script(
            'mobile: shell',
            {
                'command': 'dumpsys media_session'
            }
        )

        # Parse metadata
        metadata = {}
        state = "Unknown"

        if not result:
            self.logger.error("Failed to get playback information")
            return None

        # Get metadata
        meta_match = re.search(r'metadata: size=\d+, description=(.*?)(?=\n)', result)
        if meta_match:
            meta_parts = meta_match.group(1).split(', ')
            if len(meta_parts) >= 3:
                metadata = {
                    'song': meta_parts[0],
                    'singer': meta_parts[1],
                    'album': meta_parts[2]
                }

        # Get playback state
        state_match = re.search(r'state=PlaybackState {state=(\d+)', result)
        if state_match:
            state_code = int(state_match.group(1))
            state = {
                0: "None",
                1: "Stopped",
                2: "Paused",
                3: "Playing",
                4: "Fast Forwarding",
                5: "Rewinding",
                6: "Buffering",
                7: "Error",
                8: "Connecting",
                9: "Skipping to Next",
                10: "Skipping to Previous",
                11: "Skipping to Queue Item"
            }.get(state_code, "Unknown")

        return {
            'song': metadata.get('song', 'Unknown'),
            'singer': metadata.get('singer', 'Unknown'),
            'album': metadata.get('album', 'Unknown'),
            'state': state
        }

    def toggle_ktv_mode(self, enable):
        """Toggle KTV mode
        Args:
            enable: bool, True to enable, False to disable
        """
        self.ktv_mode = enable
        print(f"KTV mode {'enabled' if enable else 'disabled'}")

        # Check if we need to switch to lyrics page when enabling KTV mode
        if enable:
            if not self.switch_to_app():
                return False
            # Try to find lyrics tool
            lyrics_tool = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['lyrics_tool']
            )

            if not lyrics_tool:
                # If not found, switch to lyrics page
                print("Not in lyrics page, switching to lyrics page...")
                result = self.switch_to_lyrics_page()
                if result and 'error' in result:
                    print(f"Error switching to lyrics page: {result['error']}")
                    return {'enabled': 'off'}  # Indicate that KTV mode could not be enabled

        return {'enabled': 'on' if enable else 'off'}

    def is_meaningful_text(self, text):
        """Check if text is meaningful
        Args:
            text: str, text to check
        Returns:
            bool: True if text seems meaningful
        """
        try:
            if len(text) < 2:  # 太短的文本认为无意义
                return False

            try:
                # 使用detect_langs获取语言概率列表
                langs = detect_langs(text)
                if not langs:
                    return False
                # 获取最可能的语言
                lang = langs[0].lang
            except:
                return False

            if 'zh' in lang:
                # 中文文本检查逻辑保持不变
                words = list(jieba.cut(text))
                if len(words) < 2 or len(words) > len(text):
                    return False
                single_char_ratio = sum(1 for w in words if len(w) == 1) / len(words)
                if single_char_ratio > 0.8:
                    return False
            else:
                # 英文文本检查逻辑保持不变
                words = text.split()
                if len(words) < 2:
                    return False
                avg_word_len = sum(len(w) for w in words) / len(words)
                if avg_word_len < 2 or avg_word_len > 15:
                    return False

            return True

        except Exception as e:
            print(f"Error checking text meaningfulness: {str(e)}")
            return False

    def check_ktv_lyrics(self):
        if not self.switch_to_app():
            self.logger.error("Failed to switch to app")
            return {
                'error': "Failed to switch to app"
            }

        """Check current lyrics in KTV mode"""
        if not self.ktv_mode:
            return None  # 如果KTV模式未开启，则不执行

        close_poster = self.try_find_element_plus('close_poster', log=False)
        if close_poster:
            self.logger.info("Closing poster...")
            close_poster.click()

        lyrics_tool = self.wait_for_element_clickable_plus('lyrics_tool')
        if not lyrics_tool:
            self.ktv_mode = False
            self.logger.error("Failed to find lyrics tool")
            return {'error': 'Cannot find lyrics tool'}

        lyrics_tool.click()
        self.logger.info("Clicked lyrics tool")

        # 尝试查找并点击歌词海报
        lyrics_poster = self.wait_for_element_clickable_plus('lyrics_poster')
        if not lyrics_poster:
            # self.ktv_mode = False
            info = self.skip_song()
            self.logger.warning(f"Failed to find lyrics poster for {info['song']} by {info['singer']}")
            return {'error': f'Skip {info['song']} by {info['singer']} due to no lyrics poster option'}

        try:
            lyrics_poster.click()
        except StaleElementReferenceException as e:
            self.ktv_mode = False
            return {'error': 'Cannot click lyrics poster option'}
        self.logger.info("Clicked lyrics poster")

        # 找到所有的lyrics_box
        close_poster = self.wait_for_element_clickable_plus('close_poster')
        if not close_poster:
            self.ktv_mode = False
            self.logger.warning("No close poster")
            return {'error': 'No close poster'}

        current_lyrics = self.wait_for_element_clickable_plus('current_lyrics')
        finished = False
        if current_lyrics:
            try:
                y_coordinate = current_lyrics.location['y']
            except StaleElementReferenceException as e:
                self.logger.error(f"Error finding y coordinate")
                self.ktv_mode = False
                return {'error': 'Cannot get current lyrics coordinate'}

            if y_coordinate < 1000:
                finished = True
                self.logger.info("Found first line, song might be finished")
        if not finished:
            screen_size = self.driver.get_window_size()
            screen_height = screen_size['height']
            # Scroll up half screen
            self.driver.swipe(
                screen_size['width'] // 2,
                screen_height * 0.60,
                screen_size['width'] // 2,
                screen_height * 0.35,
                400
            )

        lyrics_boxes = self.driver.find_elements(
            AppiumBy.ID,
            self.config['elements']['lyrics_box']
        )

        if len(lyrics_boxes) <= 1:
            self.ktv_mode = False
            return {'error': 'Cannot find lyrics box'}

        # last element is a mistake
        lyrics_boxes.pop()

        found = False
        text = ""
        n = 0
        if not finished:
            for lyrics_box in lyrics_boxes:
                # 检查是否包含current_lyrics

                if found:
                    current_line = self.find_child_element(
                        lyrics_box,
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )
                    if current_line:
                        text += current_line.text + '\n'
                        n += 1
                else:
                    current_lyrics = self.find_child_element(
                        lyrics_box,
                        AppiumBy.ID,
                        self.config['elements']['current_lyrics']
                    )
                    if current_lyrics:
                        found = True

        if not found or finished:
            for lyrics_box in lyrics_boxes:
                current_line = self.find_child_element(
                    lyrics_box,
                    AppiumBy.ID,
                    self.config['elements']['lyrics_line']
                )
                if current_line:
                    text += current_line.text + '\n'

        if text:
            if text == self.last_lyrics:
                return {
                    'lyrics': 'Playing interlude..'
                }
            else:
                self.last_lyrics = text
                close_poster.click()
                # return all_lines
                return {
                    'lyrics': text
                }

        self.logger.error(f"lyrics is unavailable")
        self.ktv_mode = False
        return {
            'error': 'lyrics is unavailable'
        }

    def switch_to_playing_page(self):
        # Press back to exit most interfaces
        self.press_back()
        search_entry = self.try_find_element(
            AppiumBy.ID,
            self.config['elements']['search_entry']
        )
        if not search_entry:
            self.press_back()
        print("Pressed back to clean up interface")

        time.sleep(0.5)  # Wait for animation
        # Try to find and click playing bar if exists
        playing_bar = self.try_find_element(
            AppiumBy.ID,
            self.config['elements']['playing_bar']
        )
        if playing_bar:
            try:
                playing_bar.click()
            except StaleElementReferenceException as e:
                self.logger.error(f"Failed to click playing bar")
                self.press_back()
                return {'error': 'Failed to switch to lyrics page, unexpected dialog might pop up'}

            self.logger.info("Found and clicked playing bar")
            time.sleep(0.5)  # Wait for animation

        # Find more menu in play panel
        more_menu = self.wait_for_element(
            AppiumBy.ID,
            self.config['elements']['more_in_play_panel']
        )
        if not more_menu:
            self.logger.error(f"playing interface is covered by unexpected dialog")
            return {'error': 'Cannot find playing interface, please try again'}

    def switch_to_lyrics_page(self):
        """
        Switch to lyrics page
        Returns:
            dict: None if successful, error dict if failed
        """
        error = self.switch_to_playing_page()
        if error:
            return error

        # Get screen dimensions for swipe
        screen_size = self.driver.get_window_size()
        start_x = int(screen_size['width'] * 0.8)  # Start from 80% of width
        end_x = int(screen_size['width'] * 0.1)  # End at 20% of width
        y = int(screen_size['height'] * 0.5)  # Middle of screen

        # Swipe to lyrics page
        self.driver.swipe(start_x, y, end_x, y, 500)  # 500ms = 0.5s
        print("Swiped to lyrics page")

        lyrics_tool = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['lyrics_tool'])
        if not lyrics_tool:
            return {'error': 'Cannot find lyrics tool, please try again'}
        return None

    def process_lyrics(self, lyrics_text, max_width=20, force_groups=0):
        """Process lyrics text into groups with width control
        Args:
            lyrics_text: str, multi-line lyrics text
            max_width: int, maximum width for each line
            force_groups: int, force number of groups, 0 for auto calculation
        Returns:
            list: list of processed lyrics groups
        """
        # Calculate total length including newlines
        from html import unescape
        lyrics_text = unescape(lyrics_text)
        total_length = len(lyrics_text)

        # Calculate number of groups
        if force_groups > 0:
            num_groups = force_groups
        else:
            num_groups = (total_length + 499) // 500  # Ceiling division

        # Calculate target size per group
        target_group_size = total_length / num_groups if num_groups > 0 else 0

        # Split lyrics into lines and remove empty lines
        lyrics_lines = [line.strip() for line in lyrics_text.split('\n') if line.strip()]

        if not lyrics_lines:
            return []

        # First pass: combine adjacent lines within max_width
        combined_lines = []
        current_line = lyrics_lines[0]

        for next_line in lyrics_lines[1:]:
            # Try combining with next line (including a space between)
            combined = current_line + " " + next_line
            if len(combined) <= max_width:
                current_line = combined
            else:
                combined_lines.append(current_line)
                current_line = next_line

        # Add the last line
        combined_lines.append(current_line)

        # Second pass: group lines with balanced length
        groups = []
        current_group = []
        current_length = 0

        for line in combined_lines:
            line_length = len(line) + 1  # +1 for newline
            new_length = current_length + line_length

            # Check if adding this line would make the group too far from target size
            if (current_length > 0 and  # Don't check first line
                    abs(new_length - target_group_size) > abs(current_length - target_group_size) and
                    len(groups) < num_groups - 1):  # Don't create new group if we're on last group
                groups.append('\n'.join(current_group))
                current_group = [line]
                current_length = len(line)
            else:
                current_group.append(line)
                current_length = new_length

        # Add the last group
        if current_group:
            groups.append('\n'.join(current_group))

        return groups

    def get_playlist_info(self):
        """Get current playlist information
        Returns:
            str: Formatted playlist info or error dict
        """
        if not self.switch_to_app():
            self.logger.error("Cannot switch to QQ music")
            return {'error': 'Failed to switch to QQ Music app'}

        # Try to find playlist entry in playing panel first
        playlist_entry = self.try_find_element_plus('playlist_entry_playing')
        if not playlist_entry:
            playlist_entry = self.try_find_element_plus('playlist_entry_floating')
        if not playlist_entry:
            self.press_back()

        playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        if not playlist_entry:
            self.navigate_to_home()
            playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        playlist_entry.click()

        # if playlist_entry:
        #     if not self.is_element_clickable(playlist_entry):
        #         self.logger.error("Playlist entry in playing panel not clickable")
        #         return {'error': 'Playlist entry in playing panel not clickable'}
        #     playlist_entry.click()
        #     self.logger.info("Clicked playlist entry in playing panel")
        # else:
        #     # Navigate to home and try floating entry
        #     self.navigate_to_home()
        #     playlist_entry = self.try_find_element_plus('playlist_entry_floating')
        #     if not playlist_entry:
        #         self.logger.error("Failed to find playlist entry")
        #         return {'error': 'Failed to find playlist entry'}
        #
        #     if not self.is_element_clickable(playlist_entry):
        #         self.logger.error("Playlist entry floating not clickable")
        #         return {'error': 'Playlist entry floating not clickable'}
        #     playlist_entry.click()
        #     self.logger.info("Clicked playlist entry floating")

        playlist_playing = self.wait_for_element_clickable_plus('playlist_playing')
        # can_scroll = True
        can_scroll = False
        if not playlist_playing:
            self.logger.error("Failed to find playlist playing")
            return {'error': 'Failed to find playlist playing'}
        try:
            playing_loc = playlist_playing.location
            playing_size = playlist_playing.size
        except StaleElementReferenceException as e:
            self.logger.warning(f"Playing indicator invisible in playlist playing, {traceback.format_exc()}")
            playing_loc = None
            playing_size = None
            can_scroll = False

        if can_scroll:
            # Find playlist title element
            playlist_header = self.try_find_element_plus('playlist_header')
            if not playlist_header:
                self.logger.error("Failed to find playlist header")
                return {'error': 'Failed to find playlist header'}

            title_loc = playlist_header.location
            # Calculate swipe coordinates
            start_x = playing_loc['x'] + playing_size['width'] // 2
            start_y = playing_loc['y']
            end_y = title_loc['y']

            # Swipe playing element up to title position
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            self.logger.info(f"Scrolled playlist from y={start_y} to y={end_y}")

        # Get all songs and singers
        items = self.driver.find_elements(AppiumBy.ID, self.config['elements']['playlist_item_container'])

        playlist_info = []
        for item in items:
            try:
                song = self.find_child_element(item, AppiumBy.ID, self.config['elements']['playlist_song'])
                if not song:
                    self.logger.warning("Failed to find song in playlist")
                    continue
                singer = self.find_child_element(item, AppiumBy.ID, self.config['elements']['playlist_singer'])
                info = f'{song.text}{singer.text}' if singer else song.text
                playlist_info.append(info)
            except StaleElementReferenceException as e:
                self.logger.warning(f"Error getting song/singer text, {len(items)} ")
                continue

        if not playlist_info:
            self.logger.error("No songs found in playlist")
            return {'error': 'No songs found in playlist'}

        self.logger.info(f"Found {len(playlist_info)} songs in playlist")
        return {'playlist': '\n'.join(playlist_info)}

    def change_play_mode(self, mode):
        """Change play mode
        Args:
            mode: int, 1 for single loop, -1 for random, 0 for list loop
        Returns:
            dict: mode info or error
        """
        if not self.switch_to_app():
            return {'error': 'Failed to switch to QQ Music app'}

        # Try to find playing bar
        playing_bar = self.try_find_element_plus('playing_bar')

        if not playing_bar:
            # Navigate to home and try again
            self.navigate_to_home()
            playing_bar = self.wait_for_element_clickable_plus('playing_bar')
            if not playing_bar:
                return {'error': 'Cannot find playing bar'}

        playing_bar.click()
        self.logger.info("Clicked playing bar")

        # Find play mode button
        play_mode = self.wait_for_element_clickable_plus('play_mode')
        if not play_mode:
            return {'error': 'Cannot find play mode button'}

        # Get current mode
        current_desc = play_mode.get_attribute('content-desc')
        target_desc = {
            1: "单曲循环",
            -1: "随机播放",
            0: "列表循环"
        }.get(mode)

        # Convert mode to display text
        mode_text = {
            1: "single loop",
            -1: "random",
            0: "list loop"
        }.get(mode, "unknown")

        # Click until we reach target mode if needed
        if current_desc != target_desc:
            while True:
                play_mode.click()
                time.sleep(0.5)  # Wait for mode to change
                new_desc = play_mode.get_attribute('content-desc')
                if new_desc == target_desc:
                    break

        return {'mode': mode_text}
