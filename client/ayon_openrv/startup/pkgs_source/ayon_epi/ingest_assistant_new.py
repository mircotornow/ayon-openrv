from __future__ import annotations

import copy
import logging
import os
import re
import shlex
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from PySide2 import QtWidgets, QtCore
from rv import commands, extra_commands
import pandas as pd
import ayon_api
import qt_utils

from source import set_pixel_aspect

SELECT_VARIANT = "Select..."
MAIN_VARIANT = "🎬 Main"
CUSTOM_VARIANT = "Custom"
DISCARD_VARIANT = "❌ Discard"
SELECT_LENS = "Select lens..."
PROJECT_NAME = "EPILOGUE"
UNDISTORT_VARIANT = "🔧 Undistort"


# Fill lens entity IDs from AYON here (target entities for shot->lens links).
LENS_ENTITY_IDS_BY_KEY = {
    "atlasmercury1.5_36mm": "db842d10f3b811f09060199b46905fa8",
    "atlasmercury1.5_42mm": "c5903ad0e63e11f0b3170926ccc42be9",
    "atlasmercury1.5_54mm": "621c10e0e63f11f0b3170926ccc42be9",
    "atlasmercury1.5_72mm": "d06463b0180111f192d1752de7d1146e",
    "atlasmercury1.5_95mm": "1fde3140f3b911f09060199b46905fa8",
    "atlasmercury1.5_138mm": "ed9e8960180111f192d1752de7d1146e",
    "zeiss1.0_10mm": "06794c90180211f1becc192131ca96cb",
    "zeiss1.0_12mm": "b23cdab0f3b811f09060199b46905fa8",
}

DEFAULT_VARIANTS = [
    MAIN_VARIANT,
    "🤖 Reference",
    "🎨 ColorReference",
    "🧼 Clean",
    CUSTOM_VARIANT,
    DISCARD_VARIANT
]

@dataclass
class IngestSource:
    """Dataclass representing an ingest source."""
    source_node: str
    media_path: Path
    variant: str = ""
    comment: str = ""
    handles: int = -1

    def set_as_view_node(self):
        """Set this source as the current view node in RV."""
        commands.setViewNode(self.source_node)


class IngestAssistant(QtWidgets.QDockWidget):
    """Dock widget for assisting with plate ingestion into AYON."""

    SETTINGS_ORG = "mircotornow"
    SETTINGS_APP = "rv-ingest"
    SETTINGS_KEY_PATH = "lastDirectory"
    SETTINGS_KEY_GEOM = "dockGeometry"

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setWindowTitle("Ingest Assistant")
        self.sources: list[IngestSource] = []
        self.current_index = 0

        self.settings = QtCore.QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        inner_widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(inner_widget)

        self.select_button = QtWidgets.QPushButton("Select Base Folder")
        self.select_button.clicked.connect(self.select_folder)
        layout.addWidget(self.select_button)

        self.path_label = QtWidgets.QLabel("No folder selected.")
        layout.addWidget(self.path_label)

        horizontal_layout = QtWidgets.QHBoxLayout()
        ayon_folder_label = QtWidgets.QLabel("Ayon Folder:")
        horizontal_layout.addWidget(ayon_folder_label)
        self.ayon_folder_input = QtWidgets.QLineEdit()
        self.ayon_folder_input.setPlaceholderText("/scenes/...")
        horizontal_layout.addWidget(self.ayon_folder_input)
        layout.addLayout(horizontal_layout)

        self.lens_dropdown = QtWidgets.QComboBox()
        self.lens_dropdown.setEditable(False)
        self.lens_dropdown.addItems([SELECT_LENS, *LENS_ENTITY_IDS_BY_KEY.keys()])
        self.lens_dropdown.currentTextChanged.connect(self._lens_changed)
        layout.addWidget(QtWidgets.QLabel("Lens:"))
        layout.addWidget(self.lens_dropdown)

        nav_layout = QtWidgets.QHBoxLayout()

        self.prev_button = QtWidgets.QPushButton("←")
        self.prev_button.setFixedSize(30, 30)
        self.prev_button.clicked.connect(self.prev_source)
        nav_layout.addWidget(self.prev_button)

        self.current_source_label = QtWidgets.QLabel("No Source")
        self.current_source_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(self.current_source_label)

        self.next_button = QtWidgets.QPushButton("→")
        self.next_button.setFixedSize(30, 30)
        self.next_button.clicked.connect(self.next_source)
        nav_layout.addWidget(self.next_button)

        layout.addLayout(nav_layout)

        # TODO: add rename functionality to csv export
        # self.rename_current_button = QtWidgets.QPushButton("Rename Current")
        # self.rename_current_button.clicked.connect(self.rename_current)
        # layout.addWidget(self.rename_current_button)
        #
        # self.rename_all_button = QtWidgets.QPushButton("Rename All")
        # self.rename_all_button.clicked.connect(self.rename_all)
        # layout.addWidget(self.rename_all_button)

        self.variant_dropdown = QtWidgets.QComboBox()
        self.variant_dropdown.addItems([SELECT_VARIANT, *DEFAULT_VARIANTS])
        self.variant_dropdown.currentTextChanged.connect(self._variant_changed)
        layout.addWidget(QtWidgets.QLabel("Variant:"))
        layout.addWidget(self.variant_dropdown)

        self.custom_variant_input = QtWidgets.QLineEdit()
        self.custom_variant_input.setPlaceholderText("Custom variant...")
        self.custom_variant_input.setVisible(False)
        self.custom_variant_input.textChanged.connect(self._variant_changed)
        layout.addWidget(self.custom_variant_input)

        self.comment_input = QtWidgets.QLineEdit()
        self.comment_input.setPlaceholderText("Version Comment")
        self.comment_input.textChanged.connect(self._comment_changed)
        layout.addWidget(self.comment_input)

        layout.addWidget(QtWidgets.QLabel("Handle Count:"))
        self.handle_spinbox = QtWidgets.QSpinBox()
        self.handle_spinbox.setMinimum(0)
        self.handle_spinbox.setMaximum(100)
        self.handle_spinbox.setValue(0)
        self.handle_spinbox.valueChanged.connect(self._handle_changed)
        layout.addWidget(self.handle_spinbox)

        self.export_button = QtWidgets.QPushButton("Export CSV")
        self.export_button.clicked.connect(self.combined_export)
        self.export_button.setEnabled(False)
        self.export_button.setToolTip("Set a lens for the shot and a variant on all sources before exporting.")
        layout.addWidget(self.export_button)

        self.current_folder = ""
        self.shot_lens = ""

        self.setWidget(inner_widget)

    @property
    def current_source(self) -> IngestSource:
        """Get the current source based on the current index.

        Returns:
            The current ingest source.
        """
        if not self.sources or self.current_index >= len(self.sources):
            raise IndexError("No active source available")
        return self.sources[self.current_index]

    def _variant_changed(self, text: str):
        """Handle variant changes in the dropdown or custom input.

        Args:
            text: The selected variant text from the dropdown or custom input.
        """
        if not self.sources:
            return

        if text == SELECT_VARIANT:
            return

        self.custom_variant_input.setVisible(self.variant_dropdown.currentText() == CUSTOM_VARIANT)

        if text != CUSTOM_VARIANT:
            self.current_source.variant = text

        if text in [MAIN_VARIANT]:
            self.handle_spinbox.setValue(8)
        else:
            self.handle_spinbox.setValue(0)

        self._update_export_state()

    def _lens_changed(self, text: str):
        """Handle lens changes in the dropdown.

        Args:
            text: The selected or typed lens value.
        """
        lens_key = self._strip_lens_prefix(text)
        if lens_key != SELECT_LENS and lens_key not in LENS_ENTITY_IDS_BY_KEY:
            return

        self.shot_lens = "" if lens_key == SELECT_LENS else lens_key
        self._apply_pixel_aspect_to_all_sources(self.shot_lens)
        self._update_export_state()

    def _strip_lens_prefix(self, lens: str) -> str:
        lens = lens.strip()
        if lens.startswith("tech / "):
            return lens.replace("tech / ", "", 1).strip()
        if lens.startswith("tech/"):
            return lens.replace("tech/", "", 1).strip()
        return lens

    def _pixel_aspect_for_lens(self, lens: str) -> Optional[float]:
        if lens.startswith("atlasmercury"):
            return 1.5
        if lens.startswith("zeiss"):
            return 1.0
        return None

    def _apply_pixel_aspect_to_all_sources(self, lens: str):
        pixel_aspect = self._pixel_aspect_for_lens(lens)
        if pixel_aspect is None:
            return
        for source in self.sources:
            set_pixel_aspect(source.source_node, pixel_aspect)

    def _link_shot_lens_after_ingest(self, project_name: str, shot_path: str, lens_key: str) -> bool:
        """Create AYON shot->lens link after ingest succeeded.

        Returns:
            True when the link call was attempted successfully, otherwise False.
        """
        lens_entity_id = LENS_ENTITY_IDS_BY_KEY[lens_key]

        shot_folder = ayon_api.get_folder_by_path(project_name, shot_path)
        shot_folder_id = shot_folder['id']

        # Remove existing links to not have duplicates
        existing_link_ids: list[dict[str, object]] = ayon_api.get_folder_links(
            project_name=project_name,
            folder_id=shot_folder_id,
            link_types=["lens"],
        )
        for link in existing_link_ids:
            ayon_api.delete_link(
                project_name=project_name,
                link_id=link["id"],
            )

        ayon_api.create_link(
            project_name=project_name,
            link_type_name="lens",
            input_id=lens_entity_id,
            input_type="folder",
            output_id=shot_folder["id"],
            output_type="folder"
        )

        ayon_api.update_folder(
            project_name=project_name,
            folder_id=shot_folder["id"],
            attrib={
                "pixelAspect": self._pixel_aspect_for_lens(lens_key)
            }
        )

        # QtWidgets.QMessageBox.information(
        #     self,
        #     "Lens Link",
        #     f"Linked lens '{lens_key}' to shot '{shot_path}'.",
        # )
        return True

    def _update_shot(
        self,
        project_name: str,
        shot_path: str,
        frame_start: int,
        frame_end: int,
        handles: int,
        new_shot: bool
    ) -> bool:
        """Update AYON shot frame range.

        Args:
            project_name: The name of the project.
            shot_path: The path of the shot.
            frame_start: The start frame of the shot.
            frame_end: The end frame of the shot.
            handles: The number of shot handles.
            new_shot: If the shot was newly created (True) or already existed (False).
        """
        shot_folder = ayon_api.get_folder_by_path(project_name, shot_path)
        if not shot_folder:
            QtWidgets.QMessageBox.warning(
                self,
                "Shot Frame Range",
                f"Shot folder not found in AYON: {shot_path}",
            )
            return False

        folder_id = shot_folder["id"]
        folder_data = shot_folder["attrib"]
        tags = set(shot_folder["tags"])

        # frame range info before
        frame_start_before = folder_data["frameStart"]
        frame_end_before = folder_data["frameEnd"]
        handle_start_before = folder_data["handleStart"]
        handle_end_before = folder_data["handleEnd"]

        if (
            frame_start_before == frame_start
            and frame_end_before == frame_end
            and handle_start_before == handles
            and handle_end_before == handles
        ):
            # Do not update if nothing changed
            return True

        payload = {
            "frameStart": frame_start,
            "frameEnd": frame_end,
            "handleStart": handles,
            "handleEnd": handles,
        }
        if not new_shot:
            # Only add tag to shot if the shot already existed.
            tags.add("changedFrameRate")

        try:
            ayon_api.update_folder(project_name=project_name, folder_id=folder_id, attrib=payload, tags=list(tags))
            # QtWidgets.QMessageBox.information(
            #     self,
            #     "Shot Frame Range",
            #     f"Updated shot range to {frame_start}-{frame_end} for '{shot_path}'.",
            # )
            return True
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Shot Frame Range",
                f"Failed to update shot frame range:\n{exc}",
            )
            return False

    def _update_export_state(self):
        """Enable export only when all non-discard sources have variant and a shot lens."""
        active_sources = [source for source in self.sources if source.variant != DISCARD_VARIANT]
        is_ready = bool(active_sources) and bool(self.shot_lens) and all(source.variant for source in active_sources)

        self.export_button.setEnabled(is_ready)
        if is_ready:
            self.export_button.setToolTip("Export csv, rename unused files and ingest into AYON.")
        else:
            self.export_button.setToolTip("Set variants on all sources and choose one shot lens before exporting.")

    def _handle_changed(self, value: int):
        """Handle changes to the handle count spinbox.

        Args:
            value: The new handle count value.
        """
        if not self.sources:
            return
        self.current_source.handles = value

    def _comment_changed(self, text: str):
        """Handle changes to the comment input field.

        Args:
            text: The new comment text.
        """
        if not self.sources:
            return
        self.current_source.comment = text

    def extract_ayon_folder_path(self, directory: Path) -> str:
        """Extract the AYON folder path from the given directory.

        Args:
            directory: The directory from which to extract the AYON folder path.

        Returns:
            str: The AYON folder path in the format "/scenes/sqXXXX/shXXXX".
        """
        for part in directory.parts:
            match = re.match(r"(\d{4})_(\d{4})", part)
            if match:
                seq, shot = match.groups()
                self.current_folder = f"{seq}_{shot}"
                return f"/scenes/sq{seq}/sh{shot}"
        raise RuntimeError("scene couldn't be found!")

    def select_folder(self):
        """Open a dialog to select a folder and load sources from it."""
        default_path = self.settings.value(self.SETTINGS_KEY_PATH, QtCore.QDir.homePath())
        directory = Path(QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder", default_path))
        if not directory:
            return
        self.settings.setValue(self.SETTINGS_KEY_PATH, directory.as_posix())
        self.path_label.setText(directory.as_posix())
        self.ayon_folder_input.setText(self.extract_ayon_folder_path(directory))

        self.load_sources(directory)
        qt_utils.getQapp().processEvents()

        lens = self.get_lens_for_source()

        self.shot_lens = lens
        self.lens_dropdown.setCurrentText(lens if lens else SELECT_LENS)

        self._update_export_state()

    def get_lens_for_source(self, source: str | None = None) -> str:
        """Get lens from metadata of given source or current source.

        e.g.:
            ("EXR/camera_lens_type", "ATLAS MRCRY 054 9147")
            ("EXR/camera_focal", "54.0 mm")

        """
        if not source:
            sources = commands.sourcesAtFrame(commands.frame())
            if not sources:
                return ""
            source = sources[0]

        lens_focal_key = "EXR/camera_focal"

        attributes = commands.sourceAttributes(source)

        for key, value in attributes:
            if key != lens_focal_key:
                continue

            try:
                mm = value.split(".")[0]
                for lens in LENS_ENTITY_IDS_BY_KEY.keys():
                    if mm in lens:
                        return lens
            except Exception:
                logging.warning(f"Failed to get lens for {lens_focal_key}: {value}")

        return ""

    def load_sources(self, base_folder: Path):
        """Load sources from a given folder.

        Note:
            We configured this for how we would receive external files to ingest.
            E.g.:
                .../0130_0110/
                    subfolder1/
                        files.#######.exr
                    subfolder2/
                        files.#######.exr
        """
        extra_commands.displayFeedback2("Loading Sources", 2.0)
        self.sources.clear()

        for subfolder in base_folder.iterdir():
            if subfolder.name.startswith("."):  # Skip hidden folders
                continue
            if not subfolder.is_dir():  # Only look for directories, skip files
                continue
            try:
                files = sorted(
                    f for f in subfolder.iterdir()
                    if f.suffix.lower() == ".exr"
                    and not f.name.startswith(".")
                )
                for f in files:
                    # Keep original frame padding width for RV sequence recognition.
                    sequence_path = re.sub(
                        r"\.(\d*)\.exr$",
                        lambda m: f".%0{len(m.group(1))}d.exr",
                        str(f),
                    )
                    source_node = commands.addSourceVerbose([sequence_path])

                    media_path = Path(commands.sourceMedia(source_node)[0])
                    src = IngestSource(
                        source_node=commands.nodeGroup(source_node),
                        media_path=media_path
                    )
                    self.sources.append(src)

                    break
            except Exception as e:
                print(f"Error loading source from {subfolder.as_posix()}: {e}")

        if self.sources:
            self.set_active_source(0)

    def set_active_source(self, index: int):
        """Set the active source at the given index.

        Args:
            index: Index of the source to set active. Must be in range [0, len(self.sources)].

        Raises:
            RuntimeError: If no source is found at the given index.
        """
        if not self.sources:
            return

        try:
            source = self.sources[index]
        except (IndexError, KeyError):
            raise RuntimeError("No source at given index.")

        self.current_index = index
        self.sources[self.current_index].set_as_view_node()
        self.variant_dropdown.setCurrentText(source.variant or SELECT_VARIANT)
        self.custom_variant_input.setText(source.variant)
        self.comment_input.setText(source.comment)
        self.handle_spinbox.setValue(source.handles)
        self._apply_pixel_aspect_to_all_sources(self.shot_lens)
        self.current_source_label.setText(f"Source {self.current_index + 1}/{len(self.sources)}")
        self._update_export_state()

    def next_source(self):
        """Set the next source as active, wrapping around if at the end."""
        if not self.sources:
            return
        self.set_active_source((self.current_index + 1) % len(self.sources))

    def prev_source(self):
        """Set the previous source as active, wrapping around if at the start."""
        if not self.sources:
            return
        self.set_active_source((self.current_index - 1) % len(self.sources))

    def combined_export(self):
        """Export the current sources to a CSV file and move unused frames.

        Note:
            For each ingest source:
              1. Move unmarked frames (by moving to /unused folder)
              2. Build CSV rows with the updated media paths and marked frame ranges.
              3. Export the CSV file.
        """
        if not self.sources:
            return

        rows = []
        shot_frame_start = None
        shot_frame_end = None

        variant_counts = {}

        export_sources = copy.copy(self.sources)

        for source in self.sources:
            # Move main variant source to the back of the list to set the shot frame start/ end correctly.
            if source.variant == MAIN_VARIANT:
                export_sources.remove(source)

                # Append undistort variant
                undistort_source = IngestSource(**asdict(source))
                undistort_source.variant = UNDISTORT_VARIANT
                export_sources.append(undistort_source)

                export_sources.append(source)

            # Discard sources are removed from the list.
            if source.variant == DISCARD_VARIANT:
                export_sources.remove(source)

            # Check for duplicate variants
            if source.variant in variant_counts:
                variant_counts[source.variant] += 1
                # Generate suffix: "b", "c", etc. -> chr(97) would be "a"
                suffix = chr(96 + variant_counts[source.variant])
                new_variant = f"{source.variant}_{suffix}"
                source.variant = new_variant
            else:
                variant_counts[source.variant] = 1

        for source in export_sources:
            # Switch to source view to check for marked frames.
            source.set_as_view_node()
            commands.redraw()
            # Get the media path as a Path object
            media_path_list = commands.sourceMedia(f"{source.source_node}_source")
            if not media_path_list:
                continue
            media_path = Path(media_path_list[0])
            frame_start = commands.frameStart()
            frame_end = commands.frameEnd()
            full_frame_set = set(range(frame_start, frame_end + 1))

            # Get the marked frames; if none available, default to full range.
            marked = set(commands.markedFrames())
            if not marked:
                marked = set(full_frame_set)

            # Remove extension and frames
            file_name = Path(media_path.stem).stem
            file_ext = media_path.suffix
            dir_path = media_path.parent
            start_frame = min(marked)
            end_frame = max(marked)
            dir_new = dir_path / "unused"
            if not dir_new.exists():
                dir_new.mkdir()

            for frame in full_frame_set.difference(marked):
                old_file7 = dir_path / f"{file_name}.{frame:07d}{file_ext}"
                new_file = dir_new / f"{file_name}.{frame:07d}{file_ext}"
                if old_file7.exists():
                    os.rename(old_file7, new_file)
                else:
                    logging.warning(f"file {old_file7} does not exist")

            for i, frame in enumerate(marked):
                # AYON exptects a frame padding for sequences and a single file path for single frames.
                frame_padding = f"{frame:07d}"
                if i != 0:
                    frame_padding = "#######"
                    break

            file_path = dir_path / f"{file_name}.{frame_padding}{file_ext}"
            shot_pixel_aspect = self._pixel_aspect_for_lens(self.shot_lens)
            row_frame_start = start_frame + source.handles if source.handles >= 0 else start_frame
            row_frame_end = end_frame - source.handles if source.handles >= 0 else end_frame
            handles = source.handles if source.handles >= 0 else 0

            if source.variant.startswith(MAIN_VARIANT):
                shot_frame_start = row_frame_start
                shot_frame_end = row_frame_end
                shot_handles = handles

            rows.append({
                "File Path": file_path,
                "Folder Path": self.ayon_folder_input.text(),
                "Task Name": "generic",
                "Product Type": "plate",
                "Variant": source.variant.split(" ")[-1],
                "Version": "",
                "Version Comment": source.comment,
                "Version Thumbnail": "",
                "Frame Start": row_frame_start,
                "Frame End": row_frame_end,
                "Handle Start": handles,
                "Handle End": handles,
                "FPS": 25,
                "Slate Exists": "FALSE",
                "Representation": "exr",
                "Representation Colorspace": "ACES2065-1",
                "Representation Tags": "review",
                "Shot Height": "",
                "Shot Width": "",
                "Shot Pixel Aspect": shot_pixel_aspect if shot_pixel_aspect is not None else ""
            })

        if not rows:
            QtWidgets.QMessageBox.warning(self, "Export", "No sources to export.")
            return

        csv_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", (dir_path / ".." / self.current_folder).as_posix(), "CSV Files (*.csv)")
        if not csv_path:
            return

        pd.DataFrame(rows).to_csv(csv_path, index=False, sep=";")
        QtWidgets.QMessageBox.information(self, "Export", f"Exported CSV to:\n{csv_path}")

        newly_created = self._create_shot_and_task(self.ayon_folder_input.text())

        if shot_frame_start is not None and shot_frame_end is not None:
            self._update_shot(project_name=PROJECT_NAME, shot_path=self.ayon_folder_input.text(),
                              frame_start=shot_frame_start, frame_end=shot_frame_end, handles=shot_handles,
                              new_shot=newly_created)

        self._link_shot_lens_after_ingest(
            project_name=PROJECT_NAME,
            shot_path=self.ayon_folder_input.text(),
            lens_key=self.shot_lens,
        )

        dialog = IngestCommandDialog()
        dialog.start_command(
            csv_path,
            project=PROJECT_NAME,
            folder_path=self.ayon_folder_input.text(),
            task="generic"
        )
        dialog.exec_()

    def _create_shot_and_task(self, shot_path: str) -> bool:
        """Create AYON shot and task for the given shot path if they don't exist.

        Args:
            shot_path: Shot path to create shot and task for.

        Returns:
            True if the shot and task were created, False if they already exist.
        """
        folder = ayon_api.get_folder_by_path(PROJECT_NAME, shot_path)
        if folder:
            return False

        # Shot folder does not exist, create it  path = "scenes/sq0100/sh0100"
        parent_path = "/".join(shot_path.split("/")[:-1])
        shot_name = shot_path.split("/")[-1]
        parent_folder = ayon_api.get_folder_by_path(PROJECT_NAME, parent_path)
        parent_id = None
        if not parent_folder:
            scenes_path = "/".join(parent_path.split("/")[:-1])
            scenes_folder = ayon_api.get_folder_by_path(PROJECT_NAME, scenes_path)
            parent_id = ayon_api.create_folder(
                project_name=PROJECT_NAME,
                name=parent_path.split("/")[-1],
                parent_id=scenes_folder["id"],
                folder_type="Sequence"
            )
            ayon_api.create_task(
                project_name=PROJECT_NAME,
                name="generic",
                task_type="Generic",
                folder_id=parent_id,
            )
            parent_folder = ayon_api.get_folder_by_path(PROJECT_NAME, parent_path)
        shot_id = ayon_api.create_folder(
            project_name=PROJECT_NAME,
            name=shot_name,
            parent_id=parent_id or parent_folder["id"],
            folder_type="Shot"
        )
        ayon_api.create_task(
            project_name=PROJECT_NAME,
            name="generic",
            task_type="Generic",
            folder_id=shot_id,
        )
        return True


class IngestCommandDialog(QtWidgets.QDialog):
    """Dialog to run the AYON ingest command with progress feedback."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ingest Command Progress")
        self.resize(600, 400)
        self.ingest_succeeded = False

        # Create a vertical layout with a progress bar and a read-only text edit.
        layout = QtWidgets.QVBoxLayout(self)

        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # indeterminate progress
        layout.addWidget(self.progress_bar)

        self.output_text = QtWidgets.QTextEdit(self)
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.process = QtCore.QProcess(self)

        # Merge stdout and stderr so we don’t miss anything
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)

        # Read both channels from a single slot
        self.process.readyRead.connect(self._read_all)

        self.process.finished.connect(self.process_finished)

        # Surface start failures and state transitions
        self.process.errorOccurred.connect(self._proc_error)
        self.process.stateChanged.connect(self._proc_state_changed)

    def build_command(self, csv_filepath: str, project: str, folder_path: str, task: str):
        """Build the command to run the AYON ingest console.

        Args:
            csv_filepath: Path to the CSV file to ingest.
            project: The project name for the AYON ingest.
            folder_path: The folder path where the files are located.
            task: The task name for the AYON ingest.

        Returns:
            The command string to execute.
        """
        console_exe = r"C:\Program Files\Ynput\AYON 1.3.2\ayon_console.exe"

        args = [
            "addon", "traypublisher", "ingestcsv",
            "--filepath", csv_filepath,
            "--project", project,
            "--folder-path", str(Path(folder_path).parent),
            "--task", task,
            "--ignore-validators"
        ]

        return console_exe, args

    def start_command(self, csv_filepath: str, project: str, folder_path: str, task: str):
        """Start the AYON ingest command with the given parameters.

        Args:
            csv_filepath: Path to the CSV file to ingest.
            project: The project name for the AYON ingest.
            folder_path: The folder path where the files are located.
            task: The task name for the AYON ingest.
        """
        program, args = self.build_command(csv_filepath, project, folder_path, task)

        # Check the program exists to catch path errors early
        if not Path(program).exists():
            self.output_text.append(f"<span style='color:red'>Executable not found: {program}</span>")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
            self.close_button.setEnabled(True)
            self.ingest_succeeded = False
            return

        # Unbuffered Python output + optional AYON logging to stdout
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("AYON_LOG_TO_STDOUT", "1")
        # Export both raw env name and token key for toolchains that resolve either style.
        self.process.setProcessEnvironment(env)

        # Optional: set working dir to the CSV’s folder
        self.process.setWorkingDirectory(str(Path(csv_filepath).parent))

        # Show the exact command
        shown_cmd = " ".join([shlex.quote(program), *[shlex.quote(a) for a in args]])
        self.output_text.append(f"Starting command:\n{shown_cmd}\n")

        # Start the process (no shlex, no quotes embedded in program)
        self.process.start(program, args)

    def _read_all(self):
        data = self.process.readAll().data().decode(errors="replace")
        if data:
            self.output_text.append(data)

    def _proc_error(self, err):
        self.output_text.append(f"<span style='color:red'>Process error: {self.process.errorString()}</span>")

    def _proc_state_changed(self, state):
        states = {
            QtCore.QProcess.NotRunning: "NotRunning",
            QtCore.QProcess.Starting: "Starting",
            QtCore.QProcess.Running: "Running",
        }
        self.output_text.append(f"[state] {states.get(state, str(state))}")

    def process_finished(self, exitCode, exitStatus):
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.ingest_succeeded = (
            exitCode == 0 and exitStatus == QtCore.QProcess.NormalExit
        )
        self.output_text.append(f"\nProcess finished with exit code {exitCode}, status {exitStatus}")
        self.close_button.setEnabled(True)
