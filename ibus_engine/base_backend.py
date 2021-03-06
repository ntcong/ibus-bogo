# vim: set expandtab softtabstop=4 shiftwidth=4:
#
# This file is part of ibus-bogo project.
#
# Copyright (C) 2012 Long T. Dam <longdt90@gmail.com>
# Copyright (C) 2012-2014 Trung Ngo <ndtrung4419@gmail.com>
# Copyright (C) 2013 Duong H. Nguyen <cmpitg@gmail.com>
# Copyright (C) 2013 Hai P. Nguyen <hainp2604@gmail.com>
# Copyright (C) 2013-2014 Hai T. Nguyen <phaikawl@gmail.com>
#
# ibus-bogo is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ibus-bogo is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ibus-bogo.  If not, see <http://www.gnu.org/licenses/>.
#

from gi.repository import IBus
import logging
import bogo

logger = logging.getLogger(__name__)


class BackspaceType:
    HARD = 0
    SOFT = 1
    UNDO = 2


class BaseBackend():

    def __init__(self, config, abbr_expander,
                 auto_corrector):
        self.config = config
        self.abbr_expander = abbr_expander
        self.auto_corrector = auto_corrector

        # History is a list/stack of 'action's, which can be commits,
        # backspaces, string expansions, string corrections, etc.
        self.history = []

        self.reset()
        super().__init__()

    def last_nth_action(self, nth):
        if len(self.history) >= nth:
            return self.history[-nth]
        else:
            return {
                "type": "none",
                "editing-string": "",
                "raw-string": ""
            }

    def last_action(self):
        return self.last_nth_action(1)

    def reset(self):
        self.history.append({
            "type": "reset",
            "raw-string": "",
            "editing-string": ""
        })

    def update_composition(self, string, raw_string=None):
        self.history.append({
            "type": "update-composition",
            "raw-string": raw_string if raw_string
                    else self.last_action()["raw-string"],
            "editing-string": string
        })

    def commit_composition(self, string, raw_string=None):
        self.history.append({
            "type": "commit-composition",
            "raw-string": raw_string if raw_string
                    else self.last_action()["raw-string"],
            "editing-string": string
        })

    def delete_prev_chars(self, count):
        pass
        # self.history.append({
        #     "type": "delete-prev-chars",
        #     "raw-string": self.raw_string,
        #     "editing-string": self.editing_string
        # })

    def process_key_event(self, keyval, modifiers):
        last_action = self.last_action()
        editing_string = last_action["editing-string"]
        raw_string = last_action["raw-string"]

        if self.is_processable_key(keyval, modifiers):

            logger.debug("Key pressed: %c", chr(keyval))
            logger.debug("Previous raw string: %s", raw_string)
            logger.debug("Previous editing string: %s", editing_string)

            # Brace shift for TELEX's ][ keys.
            # When typing with capslock on, ][ won't get shifted to }{
            # resulting in weird capitalization in "TưởNG". So we have to
            # shift them manually.
            keyval, brace_shift = self.do_brace_shift(keyval, modifiers)

            # Invoke BoGo to process the input
            new_string, new_raw_string = \
                bogo.process_key(
                    string=editing_string,
                    key=chr(keyval),
                    fallback_sequence=raw_string,
                    rules=self.config["input-method-definition"],
                    skip_non_vietnamese=self.config["skip-non-vietnamese"])

            # Revert the brace shift
            if brace_shift and new_string and new_string[-1] in "{}":
                logger.debug("Reverting brace shift")
                new_string = new_string[:-1] + \
                    chr(ord(new_string[-1]) - 0x20)

            logger.debug("New string: %s", new_string)

            self.update_composition(
                string=new_string,
                raw_string=new_raw_string)
            return True
        else:
            return self.on_special_key_pressed(keyval)

    def do_brace_shift(self, keyval, modifiers):
        capital_case = 0
        caps_lock = modifiers & IBus.ModifierType.LOCK_MASK
        shift = modifiers & IBus.ModifierType.SHIFT_MASK
        if (caps_lock or shift) and not (caps_lock and shift):
            capital_case = 1

        brace_shift = False
        if chr(keyval) in ['[', ']'] and capital_case == 1:
            keyval = keyval + 0x20
            brace_shift = True

        return keyval, brace_shift

    # This messes up Pidgin
    # def do_reset(self):
    #     logger.debug("Reset signal")
    #     self.reset()

    def is_processable_key(self, keyval, state):
        # We accept a-Z and all the keys used in the current
        # input mode.
        im_keys = self.config["input-method-definition"]
        return \
            not state & IBus.ModifierType.CONTROL_MASK and \
            not state & IBus.ModifierType.MOD1_MASK and \
            (keyval in range(65, 91) or 
             keyval in range(97, 123) or 
             chr(keyval) in im_keys)

    def undo_last_action(self):
        last_action = self.last_action()

        # If the last commited string is a spellchecker suggestion
        # then this backspace is to undo that.
        if last_action["type"] == "string-correction":
            logger.debug("Undoing spell correction")

            # string-correction is always preceded by an
            # update-composition
            target_action = self.last_nth_action(3)

            self.commit_composition(
                target_action["editing-string"])

            self.auto_corrector.increase_ticket(
                target_action["editing-string"])

            self.history.append({
                "type": "undo",
                "raw-string": target_action["editing-string"],
                "editing-string": target_action["editing-string"]
            })

            return True

        return False

    def on_backspace_pressed(self):
        """
        Return BackspaceType - whether to do a "HARD" or "SOFT" backspace
                               or nothing on "UNDO".
        """
        logger.debug("Getting a backspace")
        editing_string = self.last_action()["editing-string"]
        raw_string = self.last_action()["raw-string"]

        if editing_string == "":
            return BackspaceType.HARD

        # Backspace is also the hotkey to undo the last action where
        # applicable.
        has_undone = self.undo_last_action()
        if has_undone:
            return BackspaceType.UNDO

        deleted_char = editing_string[-1]
        editing_string = editing_string[:-1]

        index = raw_string.rfind(deleted_char)
        raw_string = raw_string[:-2] if index < 0 else \
            raw_string[:index] + \
            raw_string[(index + 1):]

        self.history.append({
            "type": "backspace",
            "raw-string": raw_string,
            "editing-string": editing_string
        })
        return BackspaceType.SOFT

    def on_space_pressed(self):
        # Wrap the string inside a list so that can_expand() can
        # modify it.
        expanded_string = [""]

        last_action = self.last_action()
        editing_string = last_action["editing-string"]
        raw_string = last_action["raw-string"]

        def can_expand():
            if self.config["enable-text-expansion"]:
                expanded_string[0] = \
                    self.abbr_expander.expand(editing_string)
                return expanded_string[0] != editing_string
            else:
                return False

        def is_non_vietnamese():
            if self.config['skip-non-vietnamese']:
                return not bogo.validation.is_valid_string(editing_string)
            else:
                return False

        if can_expand():
            self.update_composition(expanded_string[0])

            self.history.append({
                "type": "string-expansion",
                "raw-string": raw_string,
                "editing-string": expanded_string[0]
            })
        elif is_non_vietnamese():
            suggested = \
                self.auto_corrector.suggest(self.last_action()["raw-string"])

            # Only save this edit as a string-correction
            # if the editing_string is actually different
            # from the raw_string.
            if suggested != raw_string:
                suggested += ' '
                self.update_composition(suggested)
                self.history.append({
                    "type": "string-correction",
                    "raw-string": raw_string,
                    "editing-string": suggested
                })
            else:
                self.update_composition(suggested)
