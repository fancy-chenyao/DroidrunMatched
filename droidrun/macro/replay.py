"""
Macro Replay Module - Replay recorded UI automation sequences.

This module provides functionality to load and replay macro JSON files
that were generated during DroidAgent trajectory recording.
"""

import json
import asyncio
import logging
import time
import os
from typing import Dict, List, Any, Optional
from droidrun.agent.utils.logging_utils import LoggingUtils
from droidrun.tools.adb import AdbTools
from droidrun.agent.utils.trajectory import Trajectory

logger = logging.getLogger("droidrun-macro")


class MacroPlayer:
    """
    A class for loading and replaying DroidRun macro sequences.

    This player can execute recorded UI actions (taps, swipes, text input, key presses)
    on Android devices using AdbTools.
    """

    def __init__(self, device_serial: str = None, delay_between_actions: float = 1.0):
        """
        Initialize the MacroPlayer.

        Args:
            device_serial: Serial number of the target device. If None, will use first available device.
            delay_between_actions: Delay in seconds between each action (default: 1.0s)
        """
        self.device_serial = device_serial
        self.delay_between_actions = delay_between_actions
        self.adb_tools = None

    def _initialize_tools(self) -> AdbTools:
        """Initialize ADB tools for the target device."""
        if self.adb_tools is None:
            self.adb_tools = AdbTools(serial=self.device_serial)
            LoggingUtils.log_info("MacroReplay", "Initialized ADB tools for device: {serial}", serial=self.device_serial)
        return self.adb_tools

    def load_macro_from_file(self, macro_file_path: str) -> Dict[str, Any]:
        """
        Load macro data from a JSON file.

        Args:
            macro_file_path: Path to the macro JSON file

        Returns:
            Dictionary containing the macro data
        """
        return Trajectory.load_macro_sequence(macro_file_path)

    def load_macro_from_folder(self, trajectory_folder: str) -> Dict[str, Any]:
        """
        Load macro data from a trajectory folder.

        Args:
            trajectory_folder: Path to the trajectory folder containing macro.json

        Returns:
            Dictionary containing the macro data
        """
        return Trajectory.load_macro_sequence(trajectory_folder)

    def replay_action(self, action: Dict[str, Any]) -> bool:
        """
        Replay a single action.

        Args:
            action: Action dictionary containing type and parameters

        Returns:
            True if action was executed successfully, False otherwise
        """
        tools = self._initialize_tools()
        action_type = action.get("action_type", action.get("type", "unknown"))

        try:

            if action_type == "start_app":
                package = action.get("package")
                activity = action.get("activity", None)
                tools.start_app(package, activity)
                return True

            elif action_type == "tap":
                x = action.get("x", 0)
                y = action.get("y", 0)
                element_text = action.get("element_text", "")

                LoggingUtils.log_info("MacroReplay", "Tapping at ({x}, {y}) - Element: '{text}'", 
                                    x=x, y=y, text=element_text)
                result = tools.tap_by_coordinates(x, y)
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            elif action_type == "swipe":
                start_x = action.get("start_x", 0)
                start_y = action.get("start_y", 0)
                end_x = action.get("end_x", 0)
                end_y = action.get("end_y", 0)
                duration_ms = action.get("duration_ms", 300)

                logger.info(
                    f"👆 Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y}) in {duration_ms} milliseconds"
                )
                result = tools.swipe(start_x, start_y, end_x, end_y, duration_ms)
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            elif action_type == "drag":
                start_x = action.get("start_x", 0)
                start_y = action.get("start_y", 0)
                end_x = action.get("end_x", 0)
                end_y = action.get("end_y", 0)
                duration_ms = action.get("duration_ms", 300)

                logger.info(
                    f"👆 Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y}) in {duration_ms} milliseconds"
                )
                result = tools.drag(start_x, start_y, end_x, end_y, duration_ms)
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            elif action_type == "input_text":
                text = action.get("text", "")

                LoggingUtils.log_info("MacroReplay", "Inputting text: '{text}'", text=text)
                result = tools.input_text(text)
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            elif action_type == "key_press":
                keycode = action.get("keycode", 0)
                key_name = action.get("key_name", "UNKNOWN")

                LoggingUtils.log_info("MacroReplay", "Pressing key: {key} (keycode: {code})", 
                                    key=key_name, code=keycode)
                result = tools.press_key(keycode)
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            elif action_type == "back":
                logger.info(f"⬅️  Pressing back button")
                result = tools.back()
                LoggingUtils.log_debug("MacroReplay", "Result: {result}", result=result)
                return True

            else:
                LoggingUtils.log_warning("MacroReplay", "Unknown action type: {type}", type=action_type)
                return False

        except Exception as e:
            LoggingUtils.log_error("MacroReplay", "Error executing action {type}: {error}", 
                                 type=action_type, error=e)
            return False

    async def replay_macro(
        self,
        macro_data: Dict[str, Any],
        start_from_step: int = 0,
        max_steps: Optional[int] = None,
    ) -> bool:
        """
        Replay a complete macro sequence.

        Args:
            macro_data: Macro data dictionary loaded from JSON
            start_from_step: Step number to start from (0-based, default: 0)
            max_steps: Maximum number of steps to execute (default: all)

        Returns:
            True if all actions were executed successfully, False otherwise
        """
        if not macro_data or "actions" not in macro_data:
            logger.error("❌ Invalid macro data - no actions found")
            return False

        actions = macro_data["actions"]
        description = macro_data.get("description", "Unknown macro")
        total_actions = len(actions)

        # Apply start_from_step and max_steps filters
        if start_from_step > 0:
            actions = actions[start_from_step:]
            LoggingUtils.log_info("MacroReplay", "Starting from step {step}", step=start_from_step + 1)

        if max_steps is not None:
            actions = actions[:max_steps]
            LoggingUtils.log_info("MacroReplay", "Limiting to {steps} steps", steps=max_steps)

        LoggingUtils.log_info("MacroReplay", "Starting macro replay: '{desc}'", desc=description)
        LoggingUtils.log_info("MacroReplay", "Total actions to execute: {current} / {total}", 
                            current=len(actions), total=total_actions)

        success_count = 0
        failed_count = 0

        for i, action in enumerate(actions, start=start_from_step + 1):
            action_type = action.get("action_type", action.get("type", "unknown"))
            description_text = action.get("description", "")

            LoggingUtils.log_info("MacroReplay", "Step {current}/{total}: {type}", 
                                current=i, total=total_actions, type=action_type)
            if description_text:
                LoggingUtils.log_info("MacroReplay", "Description: {desc}", desc=description_text)

            # Execute the action
            success = self.replay_action(action)

            if success:
                success_count += 1
                LoggingUtils.log_success("MacroReplay", "Action completed successfully")
            else:
                failed_count += 1
                LoggingUtils.log_error("MacroReplay", "Action failed")

            # Wait between actions (except for the last one)
            if i < len(actions):
                LoggingUtils.log_debug("MacroReplay", "Waiting {delay}s...", delay=self.delay_between_actions)
                await asyncio.sleep(self.delay_between_actions)

        # Summary
        total_executed = success_count + failed_count
        success_rate = (
            (success_count / total_executed * 100) if total_executed > 0 else 0
        )

        logger.info(f"\n🎉 Macro replay completed!")
        logger.info(
            f"📊 Success: {success_count}/{total_executed} ({success_rate:.1f}%)"
        )

        if failed_count > 0:
            LoggingUtils.log_warning("MacroReplay", "Failed actions: {count}", count=failed_count)

        return failed_count == 0


# Utility functions for convenience


async def replay_macro_file(
    macro_file_path: str,
    device_serial: str = None,
    delay_between_actions: float = 1.0,
    start_from_step: int = 0,
    max_steps: Optional[int] = None,
) -> bool:
    """
    Convenience function to replay a macro from a file.

    Args:
        macro_file_path: Path to the macro JSON file
        device_serial: Target device serial (optional)
        delay_between_actions: Delay between actions in seconds
        start_from_step: Step to start from (0-based)
        max_steps: Maximum steps to execute

    Returns:
        True if replay was successful, False otherwise
    """
    player = MacroPlayer(
        device_serial=device_serial, delay_between_actions=delay_between_actions
    )

    try:
        macro_data = player.load_macro_from_file(macro_file_path)
        return await player.replay_macro(
            macro_data, start_from_step=start_from_step, max_steps=max_steps
        )
    except Exception as e:
        LoggingUtils.log_error("MacroReplay", "Error replaying macro file {path}: {error}", 
                             path=macro_file_path, error=e)
        return False


async def replay_macro_folder(
    trajectory_folder: str,
    device_serial: str = None,
    delay_between_actions: float = 1.0,
    start_from_step: int = 0,
    max_steps: Optional[int] = None,
) -> bool:
    """
    Convenience function to replay a macro from a trajectory folder.

    Args:
        trajectory_folder: Path to the trajectory folder containing macro.json
        device_serial: Target device serial (optional)
        delay_between_actions: Delay between actions in seconds
        start_from_step: Step to start from (0-based)
        max_steps: Maximum steps to execute

    Returns:
        True if replay was successful, False otherwise
    """
    player = MacroPlayer(
        device_serial=device_serial, delay_between_actions=delay_between_actions
    )

    try:
        macro_data = player.load_macro_from_folder(trajectory_folder)
        return await player.replay_macro(
            macro_data, start_from_step=start_from_step, max_steps=max_steps
        )
    except Exception as e:
        LoggingUtils.log_error("MacroReplay", "Error replaying macro folder {folder}: {error}", 
                             folder=trajectory_folder, error=e)
        return False
