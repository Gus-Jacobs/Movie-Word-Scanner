import os
import sys
import json
import ffmpeg
import whisper
import webbrowser
import uuid
import hashlib
import glob
import requests
import smtplib
import uuid
import hashlib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QTextEdit, QWidget, QMessageBox,
    QInputDialog, QDialog, QFrame, QSlider, QSizePolicy, QGroupBox, 
    QSplitter, QComboBox, QGraphicsView, QGraphicsScene, QGraphicsLineItem,
    QGraphicsTextItem, QProgressDialog, QLineEdit, QFormLayout, QRadioButton,
    QButtonGroup, QStackedWidget, QScrollArea, QToolButton
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QFont, QMouseEvent, QColor, QPen, QBrush, QCursor,
    QPainter, QLinearGradient, QPainterPath
)
from PyQt6.QtCore import (
    Qt, QSize, QTimer, QUrl, QTime, QPointF, QLineF, QRectF, QPropertyAnimation,
    QEasingCurve, QMargins
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import QTimer
from PyQt6.QtCore import QThread, pyqtSignal, QUrl

if getattr(sys, 'frozen', False):
    # Running as a PyInstaller bundle
    BUNDLE_ROOT = sys._MEIPASS
else:
    # Running as a script
    BUNDLE_ROOT = os.path.dirname(os.path.abspath(__file__))

os.environ['QT_LOGGING_RULES'] = 'qt.multimedia.ffmpeg=false'

WORD_TEMPLATES = {
    "Custom": [],
    "Low": ["fuck", "fucking", "god damn", "goddamn", "shit", "bitch"],
    "Medium": ["fuck", "fucking", "shit", "bitch", "asshole", "bastard", "dick"],
    "Strict": ["fuck", "fucking", "shit", "bitch", "asshole", "bastard", "dick",
               "cunt", "piss", "cock", "pussy", "whore", "slut", "damn", "hell"]
}

TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Paths to bundled executables/models
FFMPEG_PATH = os.path.join(BUNDLE_ROOT, "ffmpeg_bin", "ffmpeg.exe") # Assumes ffmpeg.exe is in ffmpeg_bin
FFPROBE_PATH = os.path.join(BUNDLE_ROOT, "ffmpeg_bin", "ffprobe.exe") # Assumes ffprobe.exe is in ffmpeg_bin
WHISPER_MODEL_DIR = os.path.join(BUNDLE_ROOT, "whisper_models") # Assumes model files are in whisper_models

# --- Set ffmpeg-python's binary locations globally ---
try:
    if os.path.exists(FFMPEG_PATH):
        ffmpeg.set_ffmpeg_bin(FFMPEG_PATH)
        print(f"INFO: ffmpeg binary globally set to: {FFMPEG_PATH}")
    else:
        print(f"ERROR: FFMPEG_PATH does not exist: {FFMPEG_PATH}. ffmpeg-python will try to find ffmpeg in PATH.")
    
    if os.path.exists(FFPROBE_PATH):
        ffmpeg.set_ffprobe_bin(FFPROBE_PATH)
        print(f"INFO: ffprobe binary globally set to: {FFPROBE_PATH}")
    else:
        print(f"ERROR: FFPROBE_PATH does not exist: {FFPROBE_PATH}. ffmpeg-python will try to find ffprobe in PATH.")
except Exception as e_setbin:
    print(f"ERROR: Could not set ffmpeg/ffprobe binary paths globally: {e_setbin}")
# --- End of global binary path setting ---

def get_device_id():
    device_file = "device_id.txt"
    if os.path.exists(device_file):
        with open(device_file, "r") as f:
            return f.read().strip()
    else:
        device_id = str(uuid.uuid4())
        with open(device_file, "w") as f:
            f.write(device_id)
        return device_id

def get_signature(email, device_id=""):
    base = email + device_id
    return hashlib.sha256(base.encode()).hexdigest()

def load_sound_replacements():
    sound_dir = "assets/sounds"
    sounds = {}
    sounds["Mute"] = None
    for file_path in glob.glob(os.path.join(sound_dir, "*.*")):
        if file_path.lower().endswith(('.mp3', '.wav', '.ogg')):
            display_name = os.path.splitext(os.path.basename(file_path))[0].capitalize()
            sounds[display_name] = file_path
    return sounds

class ScanWorker(QThread):
    finished = pyqtSignal(dict, str)  # (timestamps, result_str)
    error = pyqtSignal(str)

    def __init__(self, file_path, word_list):
        super().__init__()
        self.file_path = file_path
        self.word_list = word_list

    def run(self):
        try:
            import whisper
            model = whisper.load_model("base", download_root=WHISPER_MODEL_DIR) # Point to bundled models
            result = model.transcribe(self.file_path, word_timestamps=True)
            timestamps = {word: [] for word in self.word_list}
            for segment in result['segments']:
                for word in segment['words']:
                    word_text = word['word'].lower().strip(' ,.!?')
                    if word_text in self.word_list:
                        timestamps[word_text].append((word['start'], word['end']))
            all_timestamps = sorted([t[0] for times in timestamps.values() for t in times])
            result_str = "Word Counts:\n"
            for word, times in timestamps.items():
                result_str += f"- '{word}': {len(times)} times\n"
                if times:
                    result_str += f"  Timestamps: {', '.join([f'{t[0]:.2f}s-{t[1]:.2f}s' for t in times])}\n"
            self.finished.emit({'timestamps': timestamps, 'all_timestamps': all_timestamps}, result_str)
        except Exception as e:
            self.error.emit(str(e))

class LoadingSpinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_spinner)
        self.setVisible(False)

    def start(self):
        self.setVisible(True)
        self.angle = 0
        self.timer.start(50)

    def stop(self):
        self.setVisible(False)
        self.timer.stop()
        self.angle = 0
        self.update()

    def update_spinner(self):
        self.angle = (self.angle + 30) % 360
        self.update()

    def paintEvent(self, event):
        if not self.isVisible():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)
        pen = QPen(QColor("#4CAF50"), 6)
        painter.setPen(pen)
        painter.drawArc(rect, self.angle * 16, 120 * 16)

class CustomTimeline(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().setBackgroundBrush(QBrush(QColor("#1e1e1e"))) # Match background
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(50)
        self.setMaximumHeight(50) # Keep timeline height fixed

        self.duration = 0.0
        self.timestamps = [] # List of timestamps (seconds)
        self.position_marker = None # Item to show current playback position

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def draw_time_markers(self):
        """Draws the main timeline line and basic markers."""
        self.scene().clear() # Clear previous drawing

        if self.duration <= 0:
            return

        scene_rect = self.sceneRect()
        timeline_y = scene_rect.center().y()

        # Draw main timeline line
        line_pen = QPen(QColor("#555555"), 2)
        self.scene().addLine(scene_rect.left(), timeline_y, scene_rect.right(), timeline_y, line_pen)

        # Add start and end time labels
        font = QFont("Segoe UI", 8)
        text_color = QColor("#cccccc")

        start_label = QGraphicsTextItem("0.0s")
        start_label.setDefaultTextColor(text_color)
        start_label.setFont(font)
        start_label.setPos(scene_rect.left() + 5, timeline_y - 20)
        self.scene().addItem(start_label)

        end_label = QGraphicsTextItem(f"{self.duration:.1f}s")
        end_label.setDefaultTextColor(text_color)
        end_label.setFont(font)
        end_label.setPos(scene_rect.right() - end_label.boundingRect().width() - 5, timeline_y - 20)
        self.scene().addItem(end_label)

    def draw_word_markers(self):
        """Draws markers for each timestamp."""
        if self.duration <= 0 or not self.timestamps:
            return

        scene_rect = self.sceneRect()
        timeline_y = scene_rect.center().y()
        timeline_width = scene_rect.width()

        marker_pen = QPen(QColor("#ff5555"), 1.5) # Red markers

        for timestamp in self.timestamps:
            # Calculate position based on percentage of duration
            if self.duration > 0:
                x_pos = scene_rect.left() + (timestamp / self.duration) * timeline_width
                # Draw a small vertical line marker
                self.scene().addLine(x_pos, timeline_y - 5, x_pos, timeline_y + 5, marker_pen)

    def update_position(self, current_time):
        """Updates the playback position marker."""
        if self.duration <= 0:
            return

        # Remove previous marker
        # Ensure marker belongs to the current scene before removing
        if self.position_marker and self.position_marker.scene() == self.scene():
            self.scene().removeItem(self.position_marker)
            self.position_marker = None

        scene_rect = self.sceneRect()
        timeline_y = scene_rect.center().y()
        timeline_width = scene_rect.width()

        # Calculate position
        if self.duration > 0:
            x_pos = scene_rect.left() + (current_time / self.duration) * timeline_width
            # Clamp position to scene bounds
            x_pos = max(scene_rect.left(), min(scene_rect.right(), x_pos))

            # Draw new marker (a vertical line)
            marker_pen = QPen(QColor("#4CAF50"), 2) # Green marker
            self.position_marker = self.scene().addLine(x_pos, timeline_y - 10, x_pos, timeline_y + 10, marker_pen)


    def resizeEvent(self, event):
        """Handles resize events to update the scene and redraw."""
        super().resizeEvent(event)
        # Update the scene rectangle to match the view size
        self.scene().setSceneRect(QRectF(self.rect())) # Convert QRect to QRectF
        # Redraw everything based on the new size
        self.draw_time_markers()
        self.draw_word_markers()
        # Note: update_position needs to be called separately when playback position changes
        # The MainWindow's update_progress method will handle this.



class SubscriptionCard(QFrame):
    def __init__(self, title, price, description, best_value=False, interactive=True, parent=None):
        super().__init__(parent)
        self.setObjectName("subscriptionCard")
        self.selected = False
        self.is_best_value = best_value # Renamed to avoid conflict
        self.is_interactive = interactive # Store interactive state
        self.status_state = None # To store 'active' or 'canceled'
        self._title = title # Store title for potential re-selection logic
        self.setMinimumHeight(175) # Enforce a minimum height for better uniformity
        self.is_current_plan = False # New flag
        # Removed setFixedSize(220, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed) # Allow horizontal expansion, fix vertical size based on content
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor) # Use default arrow cursor when not interactive

        self.setStyleSheet("""
            QFrame#subscriptionCard {
                background-color: #23272f;
                border: 2px solid #444;
                border-radius: 14px;
                /* transition: border-color 0.2s; */ 
                /* box-sizing: border-box; */ 
            }
            QFrame#subscriptionCard[selected="true"] { 
                /* Default selected state - border color will be handled by statusState */
                border: 2.5px solid #007bff; /* Blue border for general selection */
                box-shadow: 0 0 8px rgba(0, 123, 255, 0.5); /* Blue glow for general selection */
            }
            QFrame#subscriptionCard[selected="true"][statusState="active"] {
                border: 2.5px solid #4CAF50; /* Green for active */
            }
            QFrame#subscriptionCard[selected="true"][statusState="canceled"] {
                border: 2.5px solid #f44336; /* Red for canceled */
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.title_label.setStyleSheet("color: #fff;")
        layout.addWidget(self.title_label)

        self.price_label = QLabel(price)
        self.price_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        # Initial color, will be updated by setStatusState
        self.price_label.setStyleSheet("color: #4CAF50;") 
        layout.addWidget(self.price_label)

        self.desc_label = QLabel(description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #bbb; font-size: 13px;")
        layout.addWidget(self.desc_label)

        if self.is_best_value:
            best_label = QLabel("★ BEST VALUE")
            best_label.setStyleSheet("""
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 2px 10px;
                border-radius: 6px;
                font-size: 12px;
                margin-top: 6px;
            """)
            self.best_value_label = best_label # Store reference
            layout.addWidget(self.best_value_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.current_plan_label = QLabel("Current Plan")
        self.current_plan_label.setStyleSheet("""
            color: #ffc107; /* Amber color */
            font-size: 11px;
            font-weight: bold;
            background-color: rgba(50, 50, 50, 0.7);
            padding: 2px 6px;
            border-radius: 4px;
        """)
        self.current_plan_label.setVisible(False) # Hidden by default
        layout.addWidget(self.current_plan_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Only connect mousePressEvent if interactive
        if interactive:
            self.mousePressEvent = self._custom_mousePressEvent
        else:
            self.mousePressEvent = None # Disable mouse events

    def setIsCurrentPlan(self, is_current):
        self.is_current_plan = is_current
        self.current_plan_label.setVisible(is_current)

    def setSelected(self, selected):
        self.selected = selected
        self.setProperty("selected", "true" if selected else "false")
        # If a status is already set, ensure it's re-applied on selection change
        if self.status_state: # Check if status_state has been set
            self.setStatusState(self.status_state) # Re-apply to ensure border color is correct
        else: # If no status_state, just polish for selection
            self.style().unpolish(self)
            self.style().polish(self)

    def _custom_mousePressEvent(self, event):
        # This method is only assigned if interactive=True
        # This method is only active if interactive=True
        self.parent().select_card(self)
        super().mousePressEvent(event)
    
    def setStatusState(self, status):
        """Sets the status state for styling (e.g., 'active', 'canceled') and re-polishes."""
        self.status_state = status
        self.setProperty("statusState", status)
        self.style().unpolish(self)
        
        active_text_color = "#4CAF50"    # Green
        canceled_text_color = "#f44336"  # Red

        # Determine color for text elements based on status
        if status == "active": # e.g., selected card in PurchaseDialog, or active plan in AccountDialog
            current_text_color = active_text_color
        elif status == "canceled": # e.g., canceled plan in AccountDialog
            current_text_color = canceled_text_color
        else: # status is None (e.g. unselected card in PurchaseDialog) or an unknown status
            current_text_color = active_text_color # Default to green for text elements

        self.price_label.setStyleSheet(f"color: {current_text_color}; font-size: 20px; font-weight: bold;")
        if hasattr(self, 'best_value_label') and self.is_best_value:
            self.best_value_label.setStyleSheet(f"background-color: {current_text_color}; color: white; font-weight: bold; padding: 2px 10px; border-radius: 6px; font-size: 12px; margin-top: 6px;")
        self.style().polish(self)


class PurchaseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Purchase License")
        self.setFixedSize(760, 340)
        self.setStyleSheet("""
            QDialog {
                background-color: #23272f;
            }
            QLabel {
                color: #fff;
                font-size: 15px;
            }
            QLineEdit {
                background-color: #2c313c;
                color: #fff;
                border: 1.5px solid #555;
                border-radius: 6px;
                padding: 7px;
                font-size: 15px;
            }
            QPushButton {
                background-color: #3c3f41;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                color: #fff;
                font-size: 15px;
                min-width: 90px;
            }
            QPushButton#positiveButton {
                background-color: #4CAF50;
                font-weight: bold;
            }
            QPushButton#negativeButton {
                background-color: #f44336;
            }
            QPushButton:hover {
                background-color: #4e5254;
            }
        """)
        self.selected_plan = "full"
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(30, 24, 30, 24)

        email_label = QLabel("Enter your email for license delivery:")
        layout.addWidget(email_label)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your@email.com")
        layout.addWidget(self.email_input)

        # Subscription cards
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(18)
        self.cards = []

        self.card_full = SubscriptionCard("Full Access", "$150", "One-time payment. Lifetime access.", best_value=False, interactive=True, parent=self)
        self.card_monthly = SubscriptionCard("Monthly", "$5/mo", "Billed monthly. Cancel anytime.", best_value=False, interactive=True, parent=self)
        self.card_yearly = SubscriptionCard("Yearly", "$50/yr", "Billed yearly. Save 17%.", best_value=True, interactive=True, parent=self)
        self.cards = [self.card_full, self.card_monthly, self.card_yearly]

        for card in self.cards:
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("negativeButton")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setObjectName("positiveButton")
        self.btn_confirm.clicked.connect(self.confirm_purchase)
        btn_layout.addWidget(self.btn_confirm)

        # Select "Full Access" by default
        self.select_card(self.card_full)
        layout.addLayout(btn_layout)

    def select_card(self, selected_card_instance): # Changed parameter name to match usage
        for card in self.cards:
            is_this_selected_card = (card == selected_card_instance)
            card.setSelected(is_this_selected_card) # Apply selection property first
            if is_this_selected_card:
                card.setStatusState("active") # Then explicitly set active state for green styling
            else:
                card.setStatusState(None)   # Clear status for non-selected cards

        # Update self.selected_plan based on which card instance is selected
        if selected_card_instance == self.card_full:
            self.selected_plan = "full"
        elif selected_card_instance == self.card_monthly:
            self.selected_plan = "monthly"
        elif selected_card_instance == self.card_yearly:
            self.selected_plan = "yearly"

    def confirm_purchase(self, intent=None): # Add intent parameter
        email = self.email_input.text().strip()
        if not email:
            QMessageBox.warning(self, "Email Required", "Please enter your email.")
            return

        # Show loading popup
        loading = QMessageBox(self)
        loading.setWindowTitle("Please Wait")
        loading.setText("Contacting server and opening payment portal...\nThis may take up to a minute.")
        # Allow user to cancel if it takes too long, or remove buttons if it should be short
        # For now, let's keep it simple and non-modal for the request.
        loading.setStandardButtons(QMessageBox.StandardButton.NoButton) # Make it unclosable by user during this phase
        loading.show()
        QApplication.processEvents()
        if self.selected_plan == "yearly":
            price_id = "price_1RRfvUAt2vKSOayIdeuqno86"  # LIVE Yearly Price ID
            mode = "subscription"
        elif self.selected_plan == "monthly":
            price_id = "price_1RRfuxAt2vKSOayIfVDConRd"  # LIVE Monthly Price ID
            mode = "subscription"
        else:
            price_id = "price_1RPrQFAt2vKSOayIdtiUK7iv"  # LIVE Full Access Price ID
            mode = "payment"

        server_url = "https://server-s2j7.onrender.com/create-checkout-session"
        print(f"PurchaseDialog: Attempting to contact {server_url} with email: {email}, price_id: {price_id}, mode: {mode}")

        payload = {
            "price_id": price_id,
            "email": email,
            "mode": mode,
            "device_id": get_device_id() # Get device ID
        } # Removed intent from payload, as we're disallowing multiple accounts per email.

        if intent: # Add intent if provided (e.g., "proceed_new_for_email")
            payload["intent"] = intent
        try:
            print(f"PurchaseDialog: Payload: {json.dumps(payload)}")
            response = requests.post(
                server_url,
                json=payload,
                timeout=30 # Add a 30-second timeout
            )
            print(f"PurchaseDialog: Response status: {response.status_code}")
            print(f"PurchaseDialog: Response content: {response.text}")

            if loading.isVisible(): loading.close() # Close loading dialog *before* showing next modal dialog

            if response.status_code == 200:
                data = response.json()
                if "url" in data:
                    checkout_url = data["url"]
                    webbrowser.open(checkout_url)
                    QMessageBox.information(self, "Continue in Browser", "A secure payment page has opened in your browser.")
                    self.accept() # Close PurchaseDialog
                else:
                    QMessageBox.critical(self, "Error", f"Payment portal URL missing in server response: {response.text}")
            
            elif response.status_code == 409: # HTTP 409 Conflict
                error_data = response.json()
                error_status = error_data.get("status")
                # Use the server's message if available, otherwise a generic one
                error_message_from_server = error_data.get("message", "This email or device may already be associated with an active license.")

                if error_status in ["email_has_licenses", "signature_has_license", "email_has_other_license"]:
                    msg_box = QMessageBox(self)
                    # msg_box.setIcon(QMessageBox.Icon.Information) # Using custom icon in text
                    msg_box.setWindowTitle("Account Information") # More general title
                    msg_box.setTextFormat(Qt.TextFormat.RichText)
                    # Ensure you have an 'assets/info_icon.png' or similar, or remove/change the <img> tag.
                    # A simple alternative for the icon if no image: <h1 style='font-size: 30px; margin-bottom: 10px;'>⚠️</h1>
                    icon_path = "assets/info_icon.png" # Define path for clarity
                    icon_html = f"<img src='{icon_path}' width='48' height='48' style='margin-bottom: 10px;'/>" if os.path.exists(icon_path) else "<h1 style='font-size: 30px; margin-bottom: 10px;'>ℹ️</h1>"

                    popup_title = "Account Notice" # Default title
                    # Use the detailed message from the server directly
                    # Make the email bold if it's present in the server's message
                    popup_message = error_message_from_server.replace(email, f"<b>{email}</b>") if email and email in error_message_from_server else error_message_from_server

                    msg_box.setText(f"""
                        <div style='text-align: center;'>
                            {icon_html}
                        </div>
                        <p style='font-size: 16px; color: #e0e0e0; text-align: center; font-weight: bold;'>
                            {popup_title}
                        </p>
                        <p style='font-size: 14px; color: #c0c0c0; text-align: center; margin-top: 8px; margin-bottom: 15px;'>
                            {popup_message}
                        </p>
                    """)
                    
                    # Styling the QMessageBox
                    msg_box.setStyleSheet("""
                        QMessageBox {
                            background-color: #282c34; /* Darker, modern background */
                            border: 1px solid #3e4451;
                            border-radius: 12px; /* More rounded */
                            padding: 25px; /* Increased padding */
                        }
                        QLabel#qt_msgbox_label { /* Target the main text label */
                            color: #e0e0e0; 
                            font-size: 14px; 
                            margin-bottom: 15px; /* Space before buttons */
                        }
                        QLabel#qt_msgbox_icon_label { /* Hide default icon if using custom in text */
                            display: none; 
                        }
                        QPushButton {
                            background-color: #4e525c; /* Muted button */
                            border: none;
                            border-radius: 8px; /* Rounded buttons */
                            padding: 10px 25px; /* Generous padding */
                            color: #ffffff;
                            font-size: 14px;
                            font-weight: bold;
                            min-width: 120px; /* Wider buttons */
                            margin: 5px 10px; /* Add horizontal margin for spacing */
                            outline: none; /* Remove focus outline */
                        }
                        QPushButton:hover { background-color: #5a5f6a; }
                        QPushButton:pressed { background-color: #434750; }
                    """)

                    btn_close = msg_box.addButton("Close", QMessageBox.ButtonRole.RejectRole) # RejectRole often places it on the left
                    btn_resend = msg_box.addButton("Resend Key", QMessageBox.ButtonRole.ActionRole)
                    # No "Manage Account" button for now, as it's informational.
                    
                    msg_box.setDefaultButton(btn_close) # Make "Close" the default
                    msg_box.exec()

                    if msg_box.clickedButton() == btn_resend:
                        try:
                            resend_response = requests.post("https://server-s2j7.onrender.com/resend-licenses-for-email", json={"email": email}, timeout=20)
                            QMessageBox.information(self, "Resend Request", resend_response.json().get("message", "Request processed."))
                        except Exception as e_resend:
                            QMessageBox.critical(self, "Error", f"Failed to request license resend: {str(e_resend)}")
                        self.reject() # Close PurchaseDialog after resend attempt & message
                    elif msg_box.clickedButton() == btn_close: # Or if the dialog is closed by other means (e.g., escape key)
                        if loading.isVisible(): loading.close() # Ensure loading is closed
                        self.reject() # Close the PurchaseDialog (already here, good)
                else: # Other 409 error
                    QMessageBox.critical(self, "Error", f"Could not initiate purchase (HTTP {response.status_code}): {error_message_from_server}")

            elif response.status_code == 400: # Specific check for "already have a license"
                error_data = response.json() # This might be for signature-specific block if server still has it
                QMessageBox.warning(self, "Purchase Blocked", error_data.get("error", "Could not initiate purchase. You might already have an active license."))
            else:
                QMessageBox.critical(self, "Error", f"Could not open payment portal (HTTP {response.status_code}): {response.text}")
        
        except requests.exceptions.Timeout:
            print("PurchaseDialog: Request timed out.")
            if loading.isVisible(): loading.close()
            QMessageBox.critical(self, "Error", "The request to the server timed out. Please check your internet connection and try again.")
        except requests.exceptions.RequestException as e: # Catch other requests errors like connection errors
            print(f"PurchaseDialog: RequestException: {str(e)}")
            if loading.isVisible(): loading.close()
            QMessageBox.critical(self, "Error", f"Could not connect to the server: {str(e)}")
        except Exception as e:
            print(f"PurchaseDialog: Generic exception: {str(e)}")
            if loading.isVisible(): loading.close() # Ensure it's closed
            QMessageBox.critical(self, "Error", f"An unexpected error occurred: {str(e)}")

class SubscriptionExpiringDialog(QDialog):
    def __init__(self, days_left, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Subscription Expiring")
        self.setFixedSize(450, 300) # Adjust size as needed
        # Apply modern styling
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                border-radius: 8px;
            }
            QLabel {
                color: #ffffff;
                font-size: 14px;
            }
            QLabel#headerLabel {
                font-size: 18px;
                font-weight: bold;
                color: #ffaa00; /* Highlight color for warning */
                margin-bottom: 10px;
            }
            QPushButton {
                background-color: #4CAF50; /* Positive action color */
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 14px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #5cb860; /* Darker green on hover */
            }
            QPushButton#closeButton {
                 background-color: #3c3f41; /* Standard button color */
            }
             QPushButton#closeButton:hover {
                 background-color: #4e5254; /* Standard button hover */
            }
        """)
        self.days_left = days_left
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        header_label = QLabel("Subscription Expiring Soon!")
        header_label.setObjectName("headerLabel")
        layout.addWidget(header_label, alignment=Qt.AlignmentFlag.AlignCenter)

        message_text = f"""
        <p>Your license will expire in <b>{self.days_left} day{'s' if self.days_left != 1 else ''}</b>.</p>
        <p>To ensure uninterrupted access, please reactivate your subscription before this date.</p>

        <p><b>How to reactivate:</b></p>
        <ol>
            <li>Click the <b>Account</b> button (👤) in the top right.</li>
            <li>Click <b>Reactivate Subscription</b>.</li>
            <li>Follow the instructions to restore your access.</li>
        </ol>

        <p><i>You will not be charged again until your current period ends.</i></p>
        """
        message_label = QLabel(message_text)
        message_label.setWordWrap(True)
        message_label.setTextFormat(Qt.TextFormat.RichText) # Enable HTML
        layout.addWidget(message_label)

        # Add a button to close the dialog
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        close_button = QPushButton("OK")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.accept) # Use accept to close the dialog
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)


class LicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter License Key")
        self.setFixedSize(420, 240)
        if os.path.exists("assets/icon.png"):
            self.setWindowIcon(QIcon("assets/icon.png"))
        self.setStyleSheet("""
            QDialog {
                background-color: #23272f;
            }
            QLabel {
                color: #fff;
                font-size: 15px;
            }
            QLineEdit {
                background-color: #2c313c;
                color: #fff;
                border: 1.5px solid #555;
                border-radius: 6px;
                padding: 7px;
                font-size: 15px;
            }
            QPushButton {
                background-color: #3c3f41;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                color: #fff;
                font-size: 15px;
                min-width: 90px;
            }
            QPushButton#positiveButton {
                background-color: #4CAF50;
                font-weight: bold;
            }
            QPushButton#negativeButton {
                background-color: #f44336;
            }
            QPushButton:hover {
                background-color: #4e5254;
            }
            QToolButton {
                background: transparent;
                border: none;
                margin-left: 0px;
                margin-bottom: 0px;
            }
            QToolButton:hover {
                background: #333;
                border-radius: 6px;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.setContentsMargins(30, 24, 30, 24)

        label = QLabel("Please enter your license key:")
        layout.addWidget(label)

        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("Enter your license key here")
        layout.addWidget(self.key_input)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_purchase = QPushButton("Purchase")
        self.btn_purchase.clicked.connect(self.open_purchase_dialog)
        btn_layout.addWidget(self.btn_purchase)
        self.btn_exit = QPushButton("Exit")
        self.btn_exit.setObjectName("negativeButton")
        self.btn_exit.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_exit)
        self.btn_confirm = QPushButton("Confirm")
        self.btn_confirm.setObjectName("positiveButton")
        self.btn_confirm.clicked.connect(self.verify_key)
        btn_layout.addWidget(self.btn_confirm)
        layout.addLayout(btn_layout)

        # Subtle contact button (bottom left)
        contact_layout = QHBoxLayout()
        self.btn_contact = QToolButton()
        self.btn_contact.setToolTip("Contact support")
        self.btn_contact.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_contact.setIconSize(QSize(22, 22))
        if os.path.exists("assets/contact_icon.png"):
            self.btn_contact.setIcon(QIcon("assets/contact_icon.png"))
        else:
            self.btn_contact.setText("✉️")
        self.btn_contact.clicked.connect(self.open_contact_dialog)
        contact_layout.addWidget(self.btn_contact, alignment=Qt.AlignmentFlag.AlignLeft)
        contact_layout.addStretch()
        layout.addLayout(contact_layout)

    def open_purchase_dialog(self):
        dialog = PurchaseDialog(self)
        dialog.exec()

    def open_contact_dialog(self):
        dialog = ContactDeveloperDialog(self)
        dialog.exec()

    def verify_key(self):
        entered_key = self.key_input.text().strip()
        if not entered_key:
            QMessageBox.warning(self, "Missing Key", "Please enter your license key.")
            return
        device_id = get_device_id()
        if entered_key == "1024":
            user_data = {
                "name": "Developer",
                "email": "dev@local",
                "license_key": entered_key,
                "license_type": "full",
                "expires": (datetime.now() + timedelta(days=365*10)).strftime("%Y-%m-%d"),
                "purchased": datetime.now().strftime("%Y-%m-%d"),
                "status": "active",
                "signature": get_signature("dev@local", device_id)
            }
            with open("user_data.json", "w") as f:
                json.dump(user_data, f)
            self.accept()
            return
        try:
            response = requests.post(
                "https://server-s2j7.onrender.com/validate-key",
                json={"license_key": entered_key}
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("valid"):
                    license_type = data.get("license_type", "full")
                    expires = data.get("expires", "")
                    status = data.get("status", "active")
                    email = data.get("email", "")
                    name_from_server = data.get("name")
                    subscription_id_from_server = data.get("subscription_id")
                    stripe_customer_id_from_server = data.get("stripe_customer_id")
                    # Fallback for missing expires
                    if not expires or not isinstance(expires, str) or not expires.strip():
                        if license_type == "full":
                            expires = "2099-12-31"
                        else:
                            expires = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
                    user_data = {
                        "name": name_from_server or "Licensed User", # Use server name if available
                        "email": email,
                        "license_key": entered_key,
                        "license_type": license_type,
                        "expires": expires,
                        "purchased": datetime.now().strftime("%Y-%m-%d"),
                        "status": status,
                        "signature": get_signature(email, device_id)
                    }
                    if subscription_id_from_server:
                        user_data["subscription_id"] = subscription_id_from_server
                    if stripe_customer_id_from_server:
                        user_data["stripe_customer_id"] = stripe_customer_id_from_server
                    with open("user_data.json", "w") as f:
                        json.dump(user_data, f)
                    if status == "canceled" and expires:
                        try:
                            expires_dt = datetime.strptime(expires, "%Y-%m-%d")
                            days_left = (expires_dt - datetime.now()).days
                            if days_left > 0:
                                QMessageBox.information(
                                    self, "Subscription Expiring",
                                    f"Your license will expire in {days_left} day{'s' if days_left != 1 else ''}.\n"
                                    "You can reactivate before this date to keep your license."
                                )
                        except Exception as e:
                            print(f"Error parsing expiry date: {e}")
                    self.accept()
                    return
                else:
                    QMessageBox.warning(self, "Invalid Key", "The license key you entered is invalid.")
            else:
                QMessageBox.critical(self, "Error", f"Server error: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not validate license key: {e}")

class SelectPlanDialog(QDialog):
    def __init__(self, current_plan_type, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Subscription Plan")
        # Increased size to accommodate cards
        self.setMinimumWidth(550) # Allow width to adjust
        self.setMinimumHeight(280) # Increased height for better card display
        self.selected_plan = None
        self.current_plan_type = current_plan_type
        self.cards = []

        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; border-radius: 10px; }
            QLabel { color: #fff; font-size: 16px; font-weight: bold; margin-bottom: 10px;}
            QPushButton {
                background-color: #333333; border: none; border-radius: 5px;
                padding: 8px 16px; color: #fff; font-size: 14px; min-width: 90px;
            }
            QPushButton#positiveButton { background-color: #4CAF50; font-weight: bold; }
            QPushButton#positiveButton:hover { background-color: #5cb860; }
            QPushButton#negativeButton { background-color: #f44336; font-weight: bold; }
            QPushButton#negativeButton:hover { background-color: #d32f2f; }
            /* Styles for SubscriptionCard within this dialog */
            QFrame#subscriptionCard {
                background-color: #2b2b2b; border: 2px solid #444; border-radius: 8px;
                min-height: 150px; /* Ensure cards have enough height */
                /* box-sizing: border-box; */ /* Unsupported */
            }
            QFrame#subscriptionCard[selected="true"] {
                border: 2.5px solid #4CAF50;
                /* box-shadow: 0 0 8px rgba(76, 175, 80, 0.5); */ /* Unsupported */
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel("Select your new plan:")
        layout.addWidget(title_label)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(15)

        # Create Monthly Card
        self.card_monthly = SubscriptionCard("Monthly", "$5/mo", "Billed monthly. Cancel anytime.", interactive=(self.current_plan_type != "monthly"), parent=self)
        if self.current_plan_type == "monthly":
            self.card_monthly.setSelected(True)
            self.card_monthly.setIsCurrentPlan(True)
        cards_layout.addWidget(self.card_monthly)
        self.cards.append(self.card_monthly)
        
        # Create Yearly Card
        self.card_yearly = SubscriptionCard("Yearly", "$50/yr", "Billed yearly. Save 17%.", best_value=True, interactive=(self.current_plan_type != "yearly"), parent=self)
        if self.current_plan_type == "yearly": self.card_yearly.setSelected(True)
        cards_layout.addWidget(self.card_yearly)
        self.cards.append(self.card_yearly)

        layout.addLayout(cards_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("negativeButton")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_confirm = QPushButton("Confirm")
        self.btn_confirm = btn_confirm # Make it an instance variable
        btn_confirm.setObjectName("positiveButton")
        btn_confirm.clicked.connect(self.confirm_selection)
        self.btn_confirm.setEnabled(False) # Initially disabled
        btn_layout.addWidget(btn_confirm)
        layout.addLayout(btn_layout)

    # This method is called by SubscriptionCard's mousePressEvent
    def select_card(self, selected_card_instance):
        # Only allow selection if the card is interactive (i.e., not the current plan)
        if not selected_card_instance.is_interactive: # Use stored interactive state
            return

        for card in self.cards:
            card.setSelected(card == selected_card_instance)

        if selected_card_instance == self.card_monthly: self.selected_plan = "monthly"
        elif selected_card_instance == self.card_yearly: self.selected_plan = "yearly"

        # Enable/disable confirm button
        if self.selected_plan and self.selected_plan != self.current_plan_type:
            self.btn_confirm.setEnabled(True)
        else:
            self.btn_confirm.setEnabled(False)

    def confirm_selection(self):
        # Only accept if a new plan (different from current) is selected
        if self.selected_plan and self.selected_plan != self.current_plan_type: self.accept()
        else:
            if not self.selected_plan:
                QMessageBox.warning(self, "No Selection", "Please select a new plan.")
            else: # Trying to confirm the current plan
                QMessageBox.information(self, "No Change", "You have selected your current plan. No changes will be made.")

class AccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Account Settings")
        self.setFixedSize(450, 480) # Increased height slightly for better spacing

        # Initialize attributes for UI elements that will be updated
        # These MUST be initialized before setup_ui() is called
        self.status_group = None
        self.status_layout = None
        self.payment_group = None
        self.payment_layout = QVBoxLayout() # Initialize QVBoxLayout directly
        print(f"DEBUG AccountDialog __init__: self.payment_layout = {self.payment_layout} (id: {id(self.payment_layout)})")
        self.user_data = {} # Initialize user_data
        self._load_user_data() # Load data before UI setup
        self.setup_ui()
        print(f"DEBUG AccountDialog __init__ after setup_ui: self.payment_layout = {self.payment_layout} (id: {id(self.payment_layout if self.payment_layout else None)})")

    def setup_ui(self):
        self.setStyleSheet("""
            /* QDialog styling ... */
            QDialog {
                background-color: #1e1e1e; /* Darker background */
                border-radius: 10px;
            }
            QLabel {
                color: #cccccc; /* Lighter grey for general text */
                font-size: 14px;
            }
            QLabel#headerLabel {
                font-size: 20px; /* Larger header */
                font-weight: bold;
                color: #ffffff; /* White for header */
                margin-bottom: 15px;
            }
            QPushButton {
                background-color: #333333; /* Dark grey button */
                border: none;
                border-radius: 5px; /* Slightly more rounded */
                padding: 8px 16px; /* More padding */
                color: #ffffff; /* White text */
                font-size: 14px;
                min-width: 80px;
                max-height: 35px; /* Consistent height */
            }
            QPushButton:hover {
                background-color: #444444; /* Lighter grey on hover */
            }
            QPushButton:pressed {
                background-color: #222222; /* Even darker on press */
            }
            QPushButton#positiveButton {
                background-color: #4CAF50; /* Green for positive actions */
                font-weight: bold;
            }
            QPushButton#positiveButton:hover {
                background-color: #5cb860; /* Darker green on hover */
            }
            QPushButton#negativeButton {
                background-color: #f44336; /* Red for negative actions */
                font-weight: bold;
            }
             QPushButton#negativeButton:hover {
                background-color: #d32f2f; /* Darker red on hover */
            }
            QLineEdit {
                background-color: #2b2b2b; /* Darker input background */
                color: #ffffff; /* White text */
                border: 1px solid #555555; /* Subtle border */
                border-radius: 5px;
                padding: 8px; /* More padding */
                font-size: 14px;
                max-height: 35px; /* Consistent height */
            }
            QLineEdit:read-only {
                color: #aaaaaa; /* Grey out read-only text */
                background-color: #252525; /* Slightly different background for read-only */
                border: 1px solid #333333;
            }
            QGroupBox {
                border: 1px solid #444444; /* Darker border */
                border-radius: 6px; /* More rounded */
                margin-top: 12px; /* More space above */
                padding-top: 18px; /* More space for title */
                padding-left: 10px;
                padding-right: 10px;
                padding-bottom: 10px; 
            }
            /* Canceled style */
            #subscriptionCard[selected="true"][statusState="canceled"] {
                border: 2.5px solid #f44336; /* Red for canceled */
                /* box-shadow: 0 0 8px rgba(244, 67, 54, 0.5); */ /* Removed unsupported */
            }
             #subscriptionCard[selected="true"] { /* Fallback if statusState not set, or for general selection */
                border: 2.5px solid #4CAF50; /* Highlight color */
                /* box-shadow: 0 0 8px rgba(76, 175, 80, 0.5); */ /* Removed unsupported */
            }
             #subscriptionCard QLabel {
                 color: #ffffff; /* White text inside card */
             }
             #subscriptionCard QLabel:first-child { /* Title */
                 font-size: 15px;
                 font-weight: bold;
             }
             #subscriptionCard QLabel:nth-child(2) { /* Price */
                 font-size: 18px;
                 font-weight: bold;
                 /* color: #4CAF50; */ /* Color will be set dynamically by setStatusState */
             }
             #subscriptionCard QLabel:nth-child(3) { /* Description */
                 font-size: 12px;
                 color: #bbbbbb; /* Lighter grey description */
             }
             #subscriptionCard QLabel:last-child { /* Best Value */
                 /* background-color: #4CAF50; */ /* Color will be set dynamically */
                 color: white;
                 font-weight: bold;
                 padding: 2px 8px;
                 border-radius: 4px;
                 font-size: 11px;
                 margin-top: 4px;
             }
        """)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Main container
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 20) # More padding
        layout.setSpacing(15) # More spacing

        # Header
        header = QLabel("Account Information")
        header.setObjectName("headerLabel")
        layout.addWidget(header)

        # Account Details Group
        account_group = QGroupBox("Account Details")
        account_layout = QFormLayout()
        account_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        account_layout.setContentsMargins(5, 5, 5, 5)
        account_layout.setSpacing(10) # More spacing
        account_layout.setVerticalSpacing(10)
        account_group.setLayout(account_layout)


        # Name field
        name_layout = QHBoxLayout()
        name_layout.setSpacing(5)
        self.name_edit = QLineEdit(self.user_data.get("name", ""))
        self.name_edit.setReadOnly(True)
        name_layout.addWidget(self.name_edit, stretch=1)

        self.btn_edit_name = QPushButton("Edit")
        self.btn_edit_name.setFixedWidth(60)
        self.btn_edit_name.clicked.connect(self.edit_name)
        name_layout.addWidget(self.btn_edit_name)
        account_layout.addRow("Name:", name_layout)

        # Email field
        email_layout = QHBoxLayout()
        email_layout.setSpacing(5)
        self.email_edit = QLineEdit(self.user_data.get("email", ""))
        self.email_edit.setReadOnly(True)
        email_layout.addWidget(self.email_edit, stretch=1)

        self.btn_edit_email = QPushButton("Edit")
        self.btn_edit_email.setFixedWidth(60)
        self.btn_edit_email.clicked.connect(self.edit_email)
        email_layout.addWidget(self.btn_edit_email)
        account_layout.addRow("Email:", email_layout)

        layout.addWidget(account_group)

        # Subscription Status Group
        self.status_group = QGroupBox("Subscription Status") # Store as instance variable
        self.status_layout = QVBoxLayout() # Store layout as instance variable
        self.status_layout.setSpacing(10)
        self.status_group.setLayout(self.status_layout)

        status = self.user_data.get("status", "inactive")
        status_color = "#4CAF50" if status == "active" else "#f44336"

        self.status_label = QLabel(status.upper())
        self.status_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {status_color};
            border: 1px solid {status_color};
            border-radius: 4px;
            padding: 3px;
            margin-bottom: 8px;
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_layout.addWidget(self.status_label)

        # Subscription plan card will be added by update_ui()

        layout.addWidget(self.status_group)

        # Payment Management Group - buttons will be added by update_ui()
        self.payment_group = QGroupBox("Payment Management")
        print(f"DEBUG AccountDialog setup_ui: self.payment_layout before setSpacing = {self.payment_layout} (id: {id(self.payment_layout if self.payment_layout else None)})")
        # self.payment_layout is already initialized in __init__
        self.payment_layout.setSpacing(8)
        self.payment_group.setLayout(self.payment_layout) # Set layout for the group
        print(f"DEBUG AccountDialog setup_ui: self.payment_layout after group.setLayout = {self.payment_layout} (id: {id(self.payment_layout if self.payment_layout else None)})")
        print(f"DEBUG AccountDialog setup_ui: self.payment_group.layout() = {self.payment_group.layout()} (id: {id(self.payment_group.layout() if self.payment_group.layout() else None)})")
        layout.addWidget(self.payment_group) # Add group to main layout

        # Sign out button
        self.btn_signout = QPushButton("Sign Out")
        self.btn_signout.setObjectName("negativeButton")
        self.btn_signout.clicked.connect(self.sign_out)
        layout.addWidget(self.btn_signout, alignment=Qt.AlignmentFlag.AlignRight)

        # Add stretch to push everything up
        layout.addStretch()

        # Set up scroll area
        scroll.setWidget(container)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)
        
        # Initial UI update after basic setup
        self.update_ui()

    def _load_user_data(self):
        """Loads user data from user_data.json into self.user_data."""
        try:
            if os.path.exists("user_data.json"):
                with open("user_data.json", "r") as f:
                    self.user_data = json.load(f)
            else:
                self.user_data = {} # Ensure it's initialized if file doesn't exist
        except Exception as e:
            print(f"Error loading user_data.json: {e}")
            self.user_data = {} # Fallback to empty dict on error

    def sign_out(self):
        # Remove user data file
        try:
            if os.path.exists("user_data.json"):
                os.remove("user_data.json")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to sign out: {e}")
        self.close()
        # Optionally, force app to re-check license
        if hasattr(self.parent(), "check_license"):
            self.parent().check_license()

    def edit_name(self):
        self.name_edit.setReadOnly(False)
        self.btn_edit_name.setText("Save")
        self.btn_edit_name.disconnect()
        self.btn_edit_name.clicked.connect(lambda: self.save_field("name", self.name_edit))

    def edit_email(self):
        self.email_edit.setReadOnly(False)
        self.btn_edit_email.setText("Save")
        self.btn_edit_email.disconnect()
        self.btn_edit_email.clicked.connect(lambda: self.save_field("email", self.email_edit))

    def save_field(self, field, edit):
        new_value = edit.text()
        if not new_value:
             QMessageBox.warning(self, "Input Required", f"Please enter a value for {field}.")
             return

        old_value = self.user_data.get(field, "") # Use .get for safety
        
        license_key = self.user_data.get("license_key")
        if not license_key:
            # If no license key, we can't update backend. Revert UI.
            edit.setText(old_value) # Revert text edit
            edit.setReadOnly(True)
            QMessageBox.warning(self, "Backend Update Failed", "Could not update on the server. Missing license key locally. Please try re-entering your license key or contact support.")
            # Reset button text even if backend fails
            if field == "name":
                self.btn_edit_name.setText("Edit")
                self.btn_edit_name.disconnect()
                self.btn_edit_name.clicked.connect(self.edit_name)
            else: # field is email
                self.btn_edit_email.setText("Edit")
                self.btn_edit_email.disconnect()
                self.btn_edit_email.clicked.connect(self.edit_email)
            return

        if field == "name":
            # Optimistically update UI for name, then call backend
            self.user_data[field] = new_value
            self.save_user_data()
            edit.setReadOnly(True)
            self.btn_edit_name.setText("Edit")
            self.btn_edit_name.disconnect()
            self.btn_edit_name.clicked.connect(self.edit_name)
            # Update backend for name
            try:
                response = requests.post(
                    "https://server-s2j7.onrender.com/update-name",
                    json={"license_key": license_key, "new_name": new_value}
                )
                if response.status_code != 200:
                    # If backend failed, revert local data and UI (though name is less critical than email)
                    self.user_data[field] = old_value # Revert data
                    self.save_user_data()
                    edit.setText(old_value) # Revert UI text
                    QMessageBox.warning(self, "Backend Update Failed", f"Failed to update name on the server: {response.text}")
            except Exception as e:
                print(f"Failed to update name in backend: {e}")
                self.user_data[field] = old_value # Revert data
                self.save_user_data()
                edit.setText(old_value) # Revert UI text
                QMessageBox.warning(self, "Backend Update Partially Failed", f"Local name updated, but failed to update name on the server: {e}")
        else: # field is email
            # Update backend for email
            try:
                response = requests.post(
                    "https://server-s2j7.onrender.com/update-email",
                    json={"license_key": license_key, "new_email": new_value}
                )
                if response.status_code == 200:
                    # Backend success, now update local data and UI
                    self.user_data[field] = new_value
                    self.save_user_data()
                    edit.setReadOnly(True)
                    self.btn_edit_email.setText("Edit")
                    self.btn_edit_email.disconnect()
                    self.btn_edit_email.clicked.connect(self.edit_email)
                else:
                    # Backend error (e.g., 409 email in use)
                    error_message = response.json().get("error", response.text)
                    QMessageBox.warning(self, "Email Update Failed", f"Could not update email: {error_message}")
                    edit.setText(old_value) # Revert UI text, keep it editable
                    # Button remains "Save", no need to change connections yet
            except Exception as e:
                print(f"Failed to update email in backend: {e}")
                QMessageBox.critical(self, "Error", f"An error occurred while updating email: {e}")
                edit.setText(old_value) # Revert UI text

    def change_plan(self):
        # Ensure necessary data is available
        license_key = self.user_data.get("license_key")

        if not license_key:
             QMessageBox.warning(self, "Action Failed", "Could not perform action. Missing license key locally. Please try re-entering your license key or contact support.")
             return # No license key, cannot proceed

        current_plan_type = self.user_data.get("license_type")
        if current_plan_type == "full":
            QMessageBox.information(self, "Plan Change Not Applicable", "Lifetime licenses cannot be changed to a subscription.")
            return

        dialog = SelectPlanDialog(current_plan_type, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_plan:
            target_plan = dialog.selected_plan
        else:
            return

        try:
            response = requests.post(
                "https://server-s2j7.onrender.com/update-subscription",
                json={
                    "target_plan_type": target_plan,
                    "license_key": license_key
                }
            )
            if response.status_code == 200 and response.json().get("success"):
                self.revalidate_license() # Revalidate to get updated license info
                QMessageBox.information(self, "Changed", "Subscription plan changed successfully.")
                # self.accept() # No need to close dialog, update_ui will refresh it
            else:
                QMessageBox.critical(self, "Error", f"Failed to change plan: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to change plan: {e}")

    def revalidate_license(self):
        """Re-fetches license data from the server and updates local user_data.json."""
        try:
            # Need the license key to revalidate
            key = self.user_data.get("license_key")
            if not key:
                 print("Revalidation skipped: Missing license key locally.")
                 return # Cannot revalidate without a key

            response = requests.post(
                "https://server-s2j7.onrender.com/validate-key",
                json={"license_key": key}
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("valid"):
                    # Preserve name and purchased date if they exist locally
                    current_user_data = {}
                    if os.path.exists("user_data.json"):
                         with open("user_data.json", "r") as f:
                             current_user_data = json.load(f)

                    # Use data from server, but prefer local name/purchased if server doesn't provide
                    # Also ensure all relevant fields from server are captured
                    new_user_data = {
                        "name": current_user_data.get("name", data.get("name", "Licensed User")),
                        "email": data.get("email", ""),
                        "license_key": key,
                        "license_type": data.get("license_type", "full"),
                        "expires": data.get("expires", ""),
                        "purchased": current_user_data.get("purchased", datetime.now().strftime("%Y-%m-%d")),
                        "status": data.get("status", "active"),
                        "signature": get_signature(data.get("email", ""), get_device_id())
                    }
                    # Preserve/update subscription_id
                    if "subscription_id" in data:
                        new_user_data["subscription_id"] = data["subscription_id"]
                    elif "subscription_id" in current_user_data:
                         new_user_data["subscription_id"] = current_user_data["subscription_id"]

                    # Preserve/update stripe_customer_id
                    if "stripe_customer_id" in data:
                        new_user_data["stripe_customer_id"] = data["stripe_customer_id"]
                    elif "stripe_customer_id" in current_user_data:
                        new_user_data["stripe_customer_id"] = current_user_data["stripe_customer_id"]

                    self.user_data = new_user_data # Update internal data
                    self.save_user_data() # Save updated data to file
                    self.update_ui() # Refresh the dialog UI

                else:
                    print("Revalidation failed: Key no longer valid on server.")
                    # Optionally handle invalid key after revalidation (e.g., sign out)
                    # self.sign_out() # Example: force sign out if key becomes invalid
            else:
                print(f"Revalidation server error: {response.text}")
        except Exception as e:
            print(f"Failed to revalidate license: {e}")
            # Optionally show a warning to the user

    def cancel_subscription(self):
        # Ensure necessary data is available
        license_key = self.user_data.get("license_key")

        if not license_key:
             QMessageBox.warning(self, "Action Failed", "Could not perform action. Missing license key locally. Please try re-entering your license key or contact support.")
             return # No license key, cannot proceed

        reply = QMessageBox.question(self, "Confirm Cancellation",
                                     "Are you sure you want to cancel your subscription?\n"
                                     "Your access will continue until the end of the current billing period.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.No:
            return # User chose not to cancel

        # Create and show a "Processing..." message dialog instance
        processing_msg_dialog = QMessageBox(self)
        processing_msg_dialog.setWindowTitle("Processing")
        processing_msg_dialog.setText("Canceling subscription, please wait...")
        processing_msg_dialog.setStandardButtons(QMessageBox.StandardButton.NoButton) # No buttons for user to click
        processing_msg_dialog.show()
        try:
            response = requests.post(
                "https://server-s2j7.onrender.com/cancel-subscription",
                json={
                    "license_key": license_key
                }
            )
            if response.status_code == 200 and response.json().get("success"):
                processing_msg_dialog.accept() # Close processing message dialog
                # Update status locally immediately for UI responsiveness
                self.user_data["status"] = "canceled"
                self.save_user_data() # Save updated data
                self.revalidate_license() # Revalidate to get updated expiry date from server
                self.update_ui() # Update UI to show canceled state and reactivate button
                
                expires_date = response.json().get("expires")
                msg = "Your subscription will be canceled at the end of the current billing period."
                if expires_date:
                    msg += f" (Expected expiry: {expires_date})"
                else: # If server couldn't determine specific expiry (should be rare with the fix)
                    msg += " (Please check your Stripe account for the exact expiry date if not shown.)"
                QMessageBox.information(self, "Canceled", msg)
                self.accept() # Close dialog on success
            else:
                processing_msg_dialog.accept() # Close processing message dialog
                QMessageBox.critical(self, "Error", f"Failed to cancel subscription: {response.text}")
        except Exception as e:
            processing_msg_dialog.accept() # Close processing message dialog
            QMessageBox.critical(self, "Error", f"Failed to cancel subscription: {e}")

    def reactivate_subscription(self):
        # Ensure necessary data is available
        license_key = self.user_data.get("license_key")

        if not license_key:
             QMessageBox.warning(self, "Action Failed", "Could not perform action. Missing license key locally. Please try re-entering your license key or contact support.")
             return # No license key, cannot proceed

        try:
            response = requests.post(
                "https://server-s2j7.onrender.com/reactivate-subscription",
                json={
                    "license_key": license_key
                }
            )
            if response.status_code == 200 and response.json().get("success"):
                # Update status locally immediately for UI responsiveness
                self.user_data["status"] = "active"
                self.save_user_data() # Save updated data
                self.revalidate_license() # Revalidate to get updated expiry date from server
                print(f"AccountDialog after revalidate_license: self.user_data = {json.dumps(self.user_data, indent=2)}") # ADD THIS LINE
                self.update_ui() # Update UI to show active state and cancel/change buttons
                QMessageBox.information(self, "Reactivated", "Subscription reactivated successfully! You will not be charged until your current period ends.")
                self.accept() # Close dialog on success
            else:
                QMessageBox.critical(self, "Error", f"Failed to reactivate subscription: {response.text}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to reactivate subscription: {e}")

    def save_user_data(self):
        try:
            with open("user_data.json", "w") as f:
                json.dump(self.user_data, f, indent=4) # Use indent for readability
        except Exception as e:
            print(f"Error saving user data: {e}")
            QMessageBox.warning(self, "Save Error", f"Failed to save account data locally: {e}")


    def update_ui(self):
        """Refreshes the UI elements based on the current self.user_data."""
        print(f"DEBUG AccountDialog: --- update_ui START ---")
        # Ensure self._load_user_data() is called to get the freshest data before any UI update logic
        self._load_user_data()
        print(f"DEBUG AccountDialog: Loaded self.user_data = {json.dumps(self.user_data, indent=2)}")
        
        self.name_edit.setText(self.user_data.get("name", ""))
        self.email_edit.setText(self.user_data.get("email", ""))


        # Ensure self.status_group and self.status_layout are valid
        if self.status_group and self.status_layout:
            # Clear old card if exists by iterating backwards
            items_to_remove = []
            for i in range(self.status_layout.count() -1, -1, -1): # Iterate backwards
                item = self.status_layout.itemAt(i)
                widget = item.widget()
                # Remove only SubscriptionCard, not the status_label
                if isinstance(widget, SubscriptionCard):
                    items_to_remove.append(item)
            for item in items_to_remove:
                item.widget().deleteLater()
                self.status_layout.removeItem(item)

        status = self.user_data.get("status", "inactive")
        status_color = "#4CAF50" if status == "active" else "#f44336"
        self.status_label.setText(status.upper())
        self.status_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {status_color};
            border: 1px solid {status_color};
            border-radius: 4px;
            padding: 3px;
            margin-bottom: 8px;
        """)

        # Add new SubscriptionCard
        plan = self.user_data.get("license_type", "None")
        status_text = self.user_data.get("status", "inactive").capitalize()
        desc = f"{status_text} subscription"
        if plan == "monthly": plan_card = SubscriptionCard("Monthly", "$5/month", desc, interactive=False)
        elif plan == "yearly": plan_card = SubscriptionCard("Yearly", "$50/year", desc, best_value=True, interactive=False)
        elif plan == "full": plan_card = SubscriptionCard("Lifetime", "$150", "One-time payment", interactive=False)
        else: plan_card = SubscriptionCard(str(plan).capitalize() if plan else "Unknown", "", desc, interactive=False) # Handle "subscription" or other types
        
        plan_card.setSelected(True)
        # plan_card.setProperty("statusState", status) # setStatusState now handles this
        
        # Explicitly call setStatusState to ensure internal state and re-polishing
        plan_card.setStatusState(status) # status is 'active' or 'canceled'
        if self.status_layout: # Use instance variable
            self.status_layout.addWidget(plan_card) # Use instance variable
        else:
            print("Error: self.status_layout is None in update_ui when trying to add plan_card")

        # Rebuild the Payment Management section
        # These attributes should have been initialized correctly in setup_ui.
        # The check below was removed as self.payment_group and self.payment_layout
        # should be guaranteed to be initialized by setup_ui before update_ui is called.
        # if not self.payment_group or not self.payment_layout:
        #     print(f"CRITICAL DEBUG AccountDialog: self.payment_group is {self.payment_group}, self.payment_layout is {self.payment_layout}. Cannot update payment section.")
        #     return
        
        layout_to_modify = self.payment_layout # This should be the QVBoxLayout set on self.payment_group

        # Use self.payment_layout directly, which should now be the correct layout from the group
        layout_to_modify = self.payment_layout

        # Clear existing buttons from self.payment_layout.
        while layout_to_modify.count():
            item = layout_to_modify.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Add new buttons based on current status (ensure self.payment_layout is valid)
        # No need for 'if self.payment_layout:' check here again, as layout_to_modify is used.
        is_subscription_type = self.user_data.get("license_type") in ["monthly", "yearly"]
        current_status = self.user_data.get("status")
        is_dev_key = self.user_data.get("license_key") == "1024"

        print(f"DEBUG AccountDialog: is_subscription_type={is_subscription_type}, current_status='{current_status}', is_dev_key={is_dev_key}")

        if is_subscription_type and not is_dev_key:
            if self.user_data.get("status") == "active":
                btn_change_plan = QPushButton("Change Subscription Plan")
                btn_change_plan.clicked.connect(self.change_plan)
                layout_to_modify.addWidget(btn_change_plan)

                btn_cancel = QPushButton("Cancel Subscription")
                btn_cancel.setObjectName("negativeButton")
                btn_cancel.clicked.connect(self.cancel_subscription)
                layout_to_modify.addWidget(btn_cancel)
                print(f"DEBUG AccountDialog: Added 'Change Plan' and 'Cancel' buttons.")
            elif self.user_data.get("status") == "canceled": # status is 'canceled'
                btn_reactivate = QPushButton("Reactivate Subscription")
                btn_reactivate.setObjectName("positiveButton")
                btn_reactivate.clicked.connect(self.reactivate_subscription)
                layout_to_modify.addWidget(btn_reactivate)
                print(f"DEBUG AccountDialog: Added 'Reactivate' button.")
            
            # Determine visibility based on button count
            should_be_visible = layout_to_modify.count() > 0
        else:
            # Hide the payment group if no relevant buttons (e.g., for "full" license or dev key)
            should_be_visible = False # Ensure it's marked to be hidden
        
        print(f"DEBUG AccountDialog: layout_to_modify.count() = {layout_to_modify.count()}, Calculated should_be_visible: {should_be_visible}")

        # Re-polish styles to apply changes
        self.style().unpolish(self)
        self.style().polish(self)

        # Set visibility of the QGroupBox AFTER polishing the main dialog
        if self.payment_group: # Ensure group exists
            self.payment_group.setVisible(should_be_visible)
            print(f"DEBUG AccountDialog update_ui: AFTER POLISH, self.payment_group.setVisible({should_be_visible}). Actual isVisible(): {self.payment_group.isVisible()}")
        else:
            print(f"DEBUG AccountDialog update_ui: self.payment_group is None, cannot set visibility.")


class ContactDeveloperDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contact Developer")
        self.setMinimumSize(450, 400) # Allow some flexibility
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; border-radius: 10px; }
            QLabel { color: #fff; font-size: 14px; margin-bottom: 3px; }
            QLineEdit, QTextEdit {
                background-color: #2b2b2b; color: #fff;
                border: 1px solid #555; border-radius: 5px;
                padding: 8px; font-size: 14px;
            }
            QTextEdit { min-height: 100px; }
            QPushButton {
                background-color: #333; border: none; border-radius: 5px;
                padding: 8px 16px; color: #fff; font-size: 14px; min-width: 90px;
            }
            QPushButton:hover { background-color: #444; }
            QPushButton#positiveButton { background-color: #4CAF50; font-weight: bold; }
            QPushButton#positiveButton:hover { background-color: #5cb860; }
            QPushButton#negativeButton { background-color: #f44336; font-weight: bold; }
            QPushButton#negativeButton:hover { background-color: #d32f2f; }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self) # Set layout on self
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title_label = QLabel("Contact Developer")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff; margin-bottom: 10px;")
        layout.addWidget(title_label)

        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        label = QLabel("Send a message to the developer:")
        label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Your Name (optional)")
        layout.addWidget(self.name_input)
        form_layout.addRow("Name:", self.name_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Your Email (optional, for reply)")
        layout.addWidget(self.email_input)
        form_layout.addRow("Email:", self.email_input)

        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Subject")
        layout.addWidget(self.subject_input)
        form_layout.addRow("Subject:", self.subject_input)
        layout.addLayout(form_layout)

        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Type your message here...")
        layout.addWidget(self.message_input)

        button_layout = QHBoxLayout() # Buttons at the bottom
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("negativeButton")
        self.btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(self.btn_cancel)

        self.btn_send = QPushButton("Send")
        self.btn_send.setObjectName("positiveButton")
        self.btn_send.clicked.connect(self.send_message)
        button_layout.addWidget(self.btn_send)

        layout.addLayout(button_layout)

    def send_message(self):
        name = self.name_input.text().strip()
        email = self.email_input.text().strip()
        subject = self.subject_input.text().strip()
        message = self.message_input.toPlainText().strip()

        if not subject or not message:
            QMessageBox.warning(self, "Incomplete", "Please enter a subject and message.")
            return

        server_url = "https://server-s2j7.onrender.com/send-contact-message" # Use the server endpoint
        payload = {
            "name": name,
            "email": email,
            "subject": subject,
            "message": message
        }

        try:
            response = requests.post(server_url, json=payload, timeout=20) # Add timeout

            QMessageBox.information(self, "Message Sent", "Your message has been sent to the developer. Thank you!")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send message: {e}")

class WordListDialog(QDialog):
    def __init__(self, word_list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Word List")
        self.setFixedSize(480, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #23272f;
            }
            QLabel {
                color: #fff;
                font-size: 15px;
            }
            QLineEdit, QTextEdit {
                background-color: #2c313c;
                color: #fff;
                border: 1.5px solid #555;
                border-radius: 8px;
                padding: 7px;
                font-size: 15px;
            }
            QComboBox {
                background-color: #2c313c;
                color: #fff;
                border: 1.5px solid #555;
                border-radius: 8px;
                padding: 4px;
                font-size: 15px;
            }
            QPushButton {
                background-color: #3c3f41;
                border: none;
                border-radius: 8px;
                padding: 10px 22px;
                color: #fff;
                font-size: 15px;
                min-width: 90px;
            }
            QPushButton#positiveButton {
                background-color: #4CAF50;
                font-weight: bold;
            }
            QPushButton#negativeButton {
                background-color: #f44336;
            }
            QPushButton#copyButton {
                background-color: #5555ff;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4e5254;
            }
        """)
        self.word_list = word_list.copy()
        self.load_settings()
        self.setup_ui()

    def load_settings(self):
        # Load persistent custom list and last template
        self.settings_path = "settings.json"
        self.custom_list = self.word_list.copy()
        self.last_template = "Custom"
        try:
            if os.path.exists(self.settings_path):
                with open(self.settings_path, "r") as f:
                    settings = json.load(f)
                    self.custom_list = settings.get("word_list", self.word_list.copy())
                    self.last_template = settings.get("current_template", "Custom")
        except Exception as e:
            print(f"Error loading word list settings: {e}")

    def save_settings(self):
        try:
            settings = {
                "word_list": self.custom_list,
                "current_template": self.template_combo.currentText()
            }
            with open(self.settings_path, "w") as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving word list settings: {e}")

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # Template selection
        template_layout = QHBoxLayout()
        template_layout.addWidget(QLabel("Template:"))
        self.template_combo = QComboBox()
        self.template_combo.addItems(list(WORD_TEMPLATES.keys()))
        # Use last template if available
        self.template_combo.setCurrentText(self.last_template if self.last_template in WORD_TEMPLATES else "Custom")
        template_layout.addWidget(self.template_combo)

        self.btn_copy = QPushButton("Copy to Custom")
        self.btn_copy.setObjectName("copyButton")
        self.btn_copy.clicked.connect(self.copy_to_custom)
        template_layout.addWidget(self.btn_copy)
        layout.addLayout(template_layout)

        # Word list editor
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Enter one word per line...")
        layout.addWidget(QLabel("Words to censor (one per line):"))
        layout.addWidget(self.text_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("negativeButton")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("positiveButton")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        # Track current template
        self.current_template = self.template_combo.currentText()

        # Set initial state
        self.on_template_changed(self.current_template)
        self.template_combo.currentTextChanged.connect(self._on_template_combo_changed)

    def _on_template_combo_changed(self, template):
        self.current_template = template
        self.on_template_changed(template)

    def on_template_changed(self, template):
        # Only update the editor if switching to a template (not Custom)
        if template == "Custom":
            self.text_edit.setReadOnly(False)
            self.text_edit.setPlainText('\n'.join(self.custom_list))
        else:
            self.text_edit.setReadOnly(True)
            self.text_edit.setPlainText('\n'.join(WORD_TEMPLATES[template]))

    def copy_to_custom(self):
        template = self.template_combo.currentText()
        if template == "Custom":
            QMessageBox.information(self, "Already Custom", "You are already editing your custom list.")
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Copy Template to Custom")
        msg_box.setText(f"You are about to copy the words from the '{template}' template to your custom list.")
        msg_box.setInformativeText("How would you like to proceed?")
        msg_box.setIcon(QMessageBox.Icon.Question) # Standard question icon
        
        # Use concise button texts
        btn_replace = msg_box.addButton("Replace", QMessageBox.ButtonRole.YesRole)
        btn_append = msg_box.addButton("Append", QMessageBox.ButtonRole.NoRole) 
        btn_cancel = msg_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole) # RejectRole is good for cancel
        
        msg_box.setDefaultButton(btn_cancel) 
        msg_box.setEscapeButton(btn_cancel) # Ensure 'Esc' or 'X' button acts as cancel

        msg_box.exec()
        clicked_button = msg_box.clickedButton()

        template_words = WORD_TEMPLATES[template][:]

        if clicked_button == btn_replace:
            self.custom_list = template_words
            print("DEBUG: Replaced custom list with template.")
        elif clicked_button == btn_append:
            # Append, but avoid duplicates
            self.custom_list += [w for w in template_words if w not in self.custom_list]
            print("DEBUG: Appended template to custom list.")
        else: # Cancel button clicked or dialog closed via 'X'
            print("DEBUG: Copy to custom canceled.")
            return # Do nothing if canceled

        # Switch to Custom and update editor
        self.template_combo.setCurrentText("Custom")
        # self.on_template_changed("Custom") will be called by the signal from setCurrentText

    def accept(self):
        # Save the current template and word list
        current_template = self.template_combo.currentText()
        self.current_template = current_template  # <-- Ensure this is always set
        if current_template == "Custom":
            self.custom_list = [w.strip() for w in self.text_edit.toPlainText().splitlines() if w.strip()]
            self.word_list = self.custom_list.copy()
        else:
            self.word_list = WORD_TEMPLATES[current_template][:]
        self.save_settings()
        super().accept()

class SoundReplacementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Change Sound Replacement")
        self.setMinimumWidth(350)
        self.setStyleSheet("""
            QDialog { background-color: #23272f; border-radius: 8px; }
            QLabel { color: #fff; font-size: 15px; }
            QComboBox {
                background-color: #2c313c; color: #fff;
                border: 1.5px solid #555; border-radius: 6px;
                padding: 7px; font-size: 15px;
            }
            QComboBox QAbstractItemView { /* Dropdown list style */
                background-color: #2c313c;
                border: 1px solid #555;
                selection-background-color: #5555ff;
                color: #fff;
                padding: 4px;
            }
            QPushButton {
                background-color: #3c3f41; border: none; border-radius: 6px;
                padding: 10px 22px; color: #fff; font-size: 15px; min-width: 90px;
            }
            QPushButton:hover { background-color: #4e5254; }
            QPushButton#positiveButton { background-color: #4CAF50; font-weight: bold; }
            QPushButton#negativeButton { background-color: #f44336; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(QLabel("Select sound to replace censored words:"))

        self.sound_combo = QComboBox()
        # Assuming parent is MainWindow and has sound_replacements
        if hasattr(parent, 'sound_replacements') and hasattr(parent, 'selected_sound'):
            self.sound_combo.addItems(parent.sound_replacements.keys())
            self.sound_combo.setCurrentText(parent.selected_sound)
        layout.addWidget(self.sound_combo)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("negativeButton")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("positiveButton")
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Movie Word Scanner")
        self.setMinimumSize(1000, 700)
        self.current_file = None
        self.timestamps = {}
        self.all_timestamps = []
        self._mute_segments = None
        self.processing_complete = False
        self.current_active_button = None
        self.temp_files = []
        self.selected_sound = "Mute"
        self.sound_replacements = load_sound_replacements()
        self.selected_sound = "Mute"
        self.loading_console_timer = None
        self.loading_console_dots = 0

        # Load settings and initialize UI
        self.load_settings()
        self.setup_ui()
        self.update_button_states()

        # Set window icon
        if os.path.exists("assets/icon.png"):
            self.setWindowIcon(QIcon("assets/icon.png"))

        # --- Check and show custom license expiring dialog ---
        try:
            if os.path.exists("user_data.json"):
                with open("user_data.json", "r") as f:
                    user_data = json.load(f)
                if user_data.get("status") == "canceled" and user_data.get("expires"):
                    expires_str = user_data["expires"]
                    try:
                        expires = datetime.strptime(expires_str, "%Y-%m-%d")
                        now = datetime.now()
                        days_left = max(0, (expires.date() - now.date()).days)
                        if 0 < days_left < 3650:  # Only show if less than 10 years left
                            # Show custom dialog instead of QMessageBox
                            expiring_dialog = SubscriptionExpiringDialog(days_left, self)
                            expiring_dialog.exec() # Use exec() to show it modally
                    except Exception as e:
                        print(f"Error parsing expiry date or showing dialog: {e}")
        except Exception as e:
            print(f"Error loading user data for expiry check: {e}")

    def show_contact_form(self):
        dialog = ContactDeveloperDialog(self)
        dialog.exec()

    def check_license(self):
        if not self.verify_license():
            QApplication.quit() 

    def verify_license(self):
        try:
            if os.path.exists("user_data.json"):
                with open("user_data.json", "r") as f:
                    user_data = json.load(f)
                    expires = datetime.strptime(user_data["expires"], "%Y-%m-%d")
                    if datetime.now() <= expires:
                        self.statusBar().showMessage(f"Welcome back, {user_data['name']}!", 5000)
                        return True
                    else:
                        # License expired: delete user data and notify backend
                        license_key = user_data.get("license_key")
                        try:
                            requests.post(
                                "https://server-s2j7.onrender.com/delete-user",
                                json={"license_key": license_key} # Send only license_key
                            )
                        except Exception as e:
                            print(f"Failed to notify backend to delete user: {e}")
                        os.remove("user_data.json")
                        QMessageBox.warning(self, "License Expired", "Your license has expired and your data has been removed. Please repurchase to continue.")
        except Exception as e:
            print(f"License check error: {e}")

        # Show license dialog
        dialog = LicenseDialog(self)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def load_settings(self):
        try:
            if os.path.exists("settings.json"):
                with open("settings.json", "r") as f:
                    settings = json.load(f)
                    self.word_list = settings.get("word_list", WORD_TEMPLATES["Low"].copy())
                    self.current_template = settings.get("current_template", "Custom")
            else:
                self.word_list = WORD_TEMPLATES["Low"].copy()
                self.current_template = "Custom"
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.word_list = WORD_TEMPLATES["Low"].copy()
            self.current_template = "Custom"

    def save_settings(self):
        try:
            settings = {
                "word_list": self.word_list,
                "current_template": self.current_template
            }
            with open("settings.json", "w") as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def setup_ui(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QPushButton {
                background-color: #3c3f41;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: #ffffff;
                font-size: 14px;
                min-width: 80px;
                min-height: 30px;
            }
            QPushButton:hover {
                background-color: #4e5254;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            QPushButton#activeButton {
                background-color: #ff5555;
                font-weight: bold;
            }
            QPushButton#nextStepButton {
                background-color: #4CAF50;
                font-weight: bold;
            }
            QPushButton#accountButton {
                background-color: #5555ff;
                font-weight: bold;
                padding: 8px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }
            QPushButton#disabledButton {
                background-color: #333333;
                color: #777777;
            }
            QPushButton#navButton {
                background-color: transparent;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
                min-width: 30px;
                min-height: 30px;
                font-size: 16px;
            }
            QPushButton#positiveButton {
                background-color: #4CAF50;
                font-weight: bold;
            }
            QPushButton#negativeButton {
                background-color: #f44336;
            }
            QLabel {
                color: #ffffff;
            }
            QTextEdit, QListWidget {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #444;
                border-radius: 4px;
                font-family: Consolas;
            }
            QFrame#navBar {
                background-color: #252525;
                border-bottom: 1px solid #444;
                padding: 12px;
            }
            QComboBox {
                background-color: #3c3f41;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px;
                min-width: 80px;
            }
            QComboBox QAbstractItemView {
                background-color: #3c3f41;
                color: #ffffff;
                selection-background-color: #555;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #555;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ff5555;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            #displayFrame {
                background-color: #1e1e1e;
                border: 2px dashed #444;
                border-radius: 8px;
            }
            QMessageBox {
                background-color: #2b2b2b;
            }
            QMessageBox QLabel {
                color: #ffffff;
            }
            QMessageBox QPushButton {
                min-width: 80px;
            }
        """)

        # Main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)
        central_widget.setLayout(main_layout)

        # Navbar
        nav_bar = QFrame()
        nav_bar.setObjectName("navBar")
        nav_bar.setFixedHeight(70)
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(8)
        nav_layout.setContentsMargins(8, 12, 8, 12)
        nav_bar.setLayout(nav_layout)

        # Contact button
        self.btn_contact = QPushButton()
        self.btn_contact.setObjectName("accountButton")
        self.btn_contact.setToolTip("Contact the developer for help or feedback")
        self.btn_contact.clicked.connect(self.show_contact_form)
        self.btn_contact.setFixedSize(40, 40)
        self.btn_contact.setStyleSheet("""
            QPushButton {
                background-color: #5555ff;
                border-radius: 4px;
                padding: 0px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }
            QPushButton:hover {
                background-color: #6666ff;
            }
        """)
        if os.path.exists("assets/contact_icon.png"):
            icon = QIcon("assets/contact_icon.png")
            self.btn_contact.setIcon(icon)
            self.btn_contact.setIconSize(QSize(24, 24))
        else:
            self.btn_contact.setText("✉️")
            self.btn_contact.setStyleSheet("""
                font-size: 16px;
                padding: 0px;
                text-align: center;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
                background-color: #5555ff;
                border-radius: 4px;
            """)
        nav_layout.addWidget(self.btn_contact)

        self.btn_open = QPushButton("Select File")
        self.btn_open.setObjectName("activeButton")
        self.btn_open.clicked.connect(self.open_file)
        self.btn_open.setToolTip("Select a video file to process")
        nav_layout.addWidget(self.btn_open)

        self.btn_word_list = QPushButton("View Words")
        self.btn_word_list.setObjectName("disabledButton")
        self.btn_word_list.clicked.connect(self.edit_words)
        self.btn_word_list.setToolTip("Edit the list of words to censor")
        nav_layout.addWidget(self.btn_word_list)

        self.btn_process = QPushButton("Begin Scan")
        self.btn_process.setObjectName("disabledButton")
        self.btn_process.clicked.connect(self.process_file)
        self.btn_process.setToolTip("Scan video for censored words")
        nav_layout.addWidget(self.btn_process)

        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("disabledButton")
        self.btn_export.clicked.connect(self.export_file)
        self.btn_export.setToolTip("Export the censored video")
        nav_layout.addWidget(self.btn_export)

        # Account button with icon
        self.btn_account = QPushButton()
        self.btn_account.setObjectName("accountButton")
        self.btn_account.setToolTip("Account Settings")
        self.btn_account.clicked.connect(self.show_account)
        self.btn_account.setFixedSize(40, 40)
        self.btn_account.setStyleSheet("""
            QPushButton {
                background-color: #5555ff;
                border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #6666ff;
            }
        """)
        if os.path.exists("assets/account_icon.png"):
            icon = QIcon("assets/account_icon.png")
            self.btn_account.setIcon(icon)
            self.btn_account.setIconSize(QSize(24, 24))
        else:
            self.btn_account.setText("👤")
            self.btn_account.setStyleSheet("""
                font-size: 16px;
                padding: 0px;
                text-align: center;
            """)
        nav_layout.addWidget(self.btn_account)

        main_layout.addWidget(nav_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setStyleSheet("QSplitter::handle { height: 4px; }")
        main_layout.addWidget(splitter)

        # Display area container
        self.display_container = QWidget()
        display_layout = QVBoxLayout(self.display_container)
        display_layout.setContentsMargins(10, 0, 10, 10)
        display_layout.setSpacing(10) # Add spacing between widgets in this layout

        # Use a stacked widget to manage different display states (thumbnail, video)
        self.display_stack = QStackedWidget()
        self.display_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # The main display frame (thumbnail, drag-and-drop, etc)
        self.display_frame = QLabel("Click to add file or drag file here")
        self.display_frame.setObjectName("displayFrame")
        self.display_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding) # Make it take available space

        # Video player
        self.video_widget = QVideoWidget()
        self.video_widget.hide()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding) # Make it take available space
        display_layout.addWidget(self.video_widget, stretch=1) # Add to layout

        # Add widgets to the stacked widget
        self.display_stack.addWidget(self.display_frame) # Index 0: Initial/Thumbnail view
        self.display_stack.addWidget(self.video_widget) # Index 1: Video Player view

        # Set initial view
        self.display_stack.setCurrentIndex(0)

        # Add stacked widget to the main display layout
        display_layout.addWidget(self.display_stack, stretch=1)

        # Set up drag-and-drop and click on the display frame (which is now inside the stack)
        self.display_frame.setStyleSheet("""
            font-size: 24px; color: #777; padding: 40px;
        """)
        self.display_frame.mousePressEvent = self.handle_display_click
        self.display_frame.setAcceptDrops(True)

        self._initialize_media_player() # Call helper to initialize media player

        # Spinner overlay (NOT added to layout, will be manually positioned)
        self.spinner = LoadingSpinner(self.display_container)
        self.spinner.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.spinner.setStyleSheet("background: transparent;")
        self.spinner.hide() # Hide initially

        # Post-scan buttons
        self.post_scan_widget = QWidget()
        post_scan_layout = QHBoxLayout()
        post_scan_layout.setContentsMargins(0, 0, 0, 0) # Adjust margins
        self.post_scan_widget.setLayout(post_scan_layout)

        self.btn_preview = QPushButton("Preview")
        self.btn_preview.setObjectName("positiveButton")
        self.btn_preview.clicked.connect(self.show_preview)
        post_scan_layout.addWidget(self.btn_preview)

        post_scan_layout.addSpacing(20)

        self.btn_quit = QPushButton("Quit")
        self.btn_quit.setObjectName("negativeButton")
        self.btn_quit.clicked.connect(self.reset_ui)
        post_scan_layout.addWidget(self.btn_quit)

        self.post_scan_widget.hide()
        display_layout.addWidget(self.post_scan_widget, alignment=Qt.AlignmentFlag.AlignCenter) # Add to layout

        # Preview navigation buttons
        self.preview_nav_widget = QWidget()
        self.preview_nav_widget.hide()
        preview_nav_layout = QHBoxLayout()
        preview_nav_layout.setContentsMargins(0, 0, 0, 0) # Adjust margins
        self.preview_nav_widget.setLayout(preview_nav_layout)

        self.btn_return = QPushButton("← Return to Menu")
        self.btn_return.clicked.connect(self.reset_ui)
        preview_nav_layout.addWidget(self.btn_return)

        preview_nav_layout.addStretch()

        self.btn_sound = QPushButton("Change Sound")
        self.btn_sound.clicked.connect(self.change_sound)
        preview_nav_layout.addWidget(self.btn_sound)

        self.btn_confirm = QPushButton("Confirm and Continue →")
        self.btn_confirm.setObjectName("positiveButton")
        self.btn_confirm.clicked.connect(self.mute_words)
        preview_nav_layout.addWidget(self.btn_confirm)

        display_layout.addWidget(self.preview_nav_widget) # Add to layout

        # Video controls
        self.controls_frame = QFrame()
        self.controls_frame.hide()
        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0) # Adjust margins
        self.controls_frame.setLayout(controls_layout)

        # Custom timeline
        self.timeline = CustomTimeline()
        controls_layout.addWidget(self.timeline)

        # Playback controls
        control_buttons = QHBoxLayout()
        control_buttons.setSpacing(10)

        self.btn_play = QPushButton("⏸")
        self.btn_play.setObjectName("navButton")
        self.btn_play.clicked.connect(self.toggle_play)
        control_buttons.addWidget(self.btn_play)

        self.btn_prev = QPushButton("◀◀")
        self.btn_prev.setObjectName("navButton")
        self.btn_prev.clicked.connect(self.prev_timestamp)
        control_buttons.addWidget(self.btn_prev)

        self.time_label = QLabel("00:00:00.000")
        control_buttons.addWidget(self.time_label)

        self.btn_next = QPushButton("▶▶")
        self.btn_next.setObjectName("navButton")
        self.btn_next.clicked.connect(self.next_timestamp)
        control_buttons.addWidget(self.btn_next)

        control_buttons.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self.set_playback_speed)
        control_buttons.addWidget(self.speed_combo)

        control_buttons.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.valueChanged.connect(self.set_volume)
        control_buttons.addWidget(self.volume_slider)

        controls_layout.addLayout(control_buttons)
        display_layout.addWidget(self.controls_frame) # Add to layout


        # Terminal
        self.terminal_group = QGroupBox("Results")
        terminal_layout = QVBoxLayout()
        self.terminal_group.setLayout(terminal_layout)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        terminal_layout.addWidget(self.terminal)

        splitter.addWidget(self.display_container) # Add display_container to splitter
        splitter.addWidget(self.terminal_group)
        splitter.setSizes([600, 200])


        # Status bar
        self.statusBar().showMessage("Ready", 3000)

    def center_spinner(self):
        """Centers the spinner within the display_container."""
        if self.spinner.isVisible():
            spinner_size = self.spinner.size()
            # Ensure display_container is valid and has a size
            if not self.display_container or self.display_container.width() == 0 or self.display_container.height() == 0:
                print("DEBUG: center_spinner - display_container not ready or has no size.")
                # Fallback to centering on main window if display_container is problematic
                # This might happen if called too early before layouts are fully processed.
                parent_rect = self.rect()
                x = parent_rect.center().x() - spinner_size.width() // 2
                y = parent_rect.center().y() - spinner_size.height() // 2
                self.spinner.move(x,y)
                self.spinner.raise_() # Ensure it's on top
                return


            container_rect = self.display_container.contentsRect()
            x = container_rect.center().x() - spinner_size.width() // 2
            y = container_rect.center().y() - spinner_size.height() // 2
            self.spinner.move(x, y)

    def resizeEvent(self, event):
        """Handle window resize to recenter the spinner."""
        super().resizeEvent(event)
        self.center_spinner()
        # Also update timeline size on resize
        if self.timeline.isVisible():
             self.timeline.resizeEvent(event) # Pass the event or handle internally

    def open_file(self):
        self.cleanup_temp_files()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Movie File", "", "Video Files (*.mp4 *.avi *.mov)"
        )
        if file_path:
            # Hide display frame and video widget, show spinner
            self.display_stack.setCurrentIndex(0) # Ensure we are on the thumbnail/initial view
            self.post_scan_widget.hide()
            self.preview_nav_widget.hide()
            self.controls_frame.hide()

            self.spinner.show()
            self.center_spinner() # Center spinner when showing
            self.spinner.start()

            self.terminal.setText("Loading file")
            self.loading_console_dots = 0
            if self.loading_console_timer is None:
                self.loading_console_timer = QTimer(self)
                self.loading_console_timer.timeout.connect(self.animate_console_loading)
            self.loading_console_timer.start(400)
            QApplication.processEvents()
            self.load_file(file_path)
            self.update_button_states()

    def load_file(self, file_path):
        self.current_file = file_path
        self.generate_thumbnail(file_path)
        self.btn_process.setEnabled(True)
        self.processing_complete = False

        # Stop spinner and loading animation
        if self.loading_console_timer:
            self.loading_console_timer.stop()
        self.terminal.setText("File loaded successfully!")

        self.spinner.stop()
        self.spinner.hide() # Hide spinner

        # Show display frame (thumbnail)
        self.display_stack.setCurrentIndex(0) # Show the thumbnail view
        self.post_scan_widget.hide()
        self.preview_nav_widget.hide()
        self.controls_frame.hide()

        self.update_button_states()

    def process_file(self):
        if not self.current_file:
            return

        self.terminal.setText("Processing... (this may take several minutes)")

        # Hide display frame and video widget, show spinner
        self.display_stack.setCurrentIndex(0) # Ensure we are on the thumbnail/initial view
        self.post_scan_widget.hide()
        self.preview_nav_widget.hide()
        self.controls_frame.hide()

        self.spinner.show()
        self.center_spinner() # Center spinner when showing
        self.spinner.start()
        QApplication.processEvents()

        # Disable buttons to prevent user interaction during scan
        self.btn_process.setEnabled(False)
        self.btn_open.setEnabled(False)
        self.btn_word_list.setEnabled(False)
        self.btn_export.setEnabled(False) # Also disable export during scan

        # Create and start the scan worker thread
        self.scan_worker = ScanWorker(self.current_file, self.word_list)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error.connect(self.on_scan_error)
        self.scan_worker.start()


    def show_account(self):
        dialog = AccountDialog(self)
        dialog.exec()

    def change_sound(self):
        dialog = SoundReplacementDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_sound = dialog.sound_combo.currentText()
            self.statusBar().showMessage(f"Sound replacement set to: {self.selected_sound}", 3000)

    def update_button_states(self):
        """Update which buttons are highlighted based on current state"""
        # Reset all buttons first
        self.btn_open.setObjectName("")
        self.btn_word_list.setObjectName("")
        self.btn_process.setObjectName("")
        self.btn_export.setObjectName("")
        
        # Set account button always to its special color
        self.btn_account.setObjectName("accountButton")
        
        # Determine which button should be active
        if not self.current_file:
            self.btn_open.setObjectName("activeButton")
            self.btn_word_list.setObjectName("disabledButton")
            self.btn_process.setObjectName("disabledButton")
            self.btn_export.setObjectName("disabledButton")
        elif not self.timestamps:
            if self.current_active_button == self.btn_open:  # Came from file selection
                self.btn_word_list.setObjectName("nextStepButton")
                self.btn_process.setObjectName("disabledButton")
            else:  # Came back from somewhere else
                self.btn_word_list.setObjectName("activeButton")
                self.btn_process.setObjectName("nextStepButton")
            self.btn_export.setObjectName("disabledButton")
        elif not self.processing_complete:
            self.btn_process.setObjectName("activeButton")
            self.btn_export.setObjectName("disabledButton")
        else:
            self.btn_export.setObjectName("nextStepButton")
            self.btn_process.setObjectName("")
        
        # Update the styles
        self.btn_open.style().unpolish(self.btn_open)
        self.btn_open.style().polish(self.btn_open)
        self.btn_word_list.style().unpolish(self.btn_word_list)
        self.btn_word_list.style().polish(self.btn_word_list)
        self.btn_process.style().unpolish(self.btn_process)
        self.btn_process.style().polish(self.btn_process)
        self.btn_export.style().unpolish(self.btn_export)
        self.btn_export.style().polish(self.btn_export)
        self.btn_account.style().unpolish(self.btn_account)
        self.btn_account.style().polish(self.btn_account)
        
        # Track the current active button for state transitions
        if self.btn_open.objectName() == "activeButton":
            self.current_active_button = self.btn_open
        elif self.btn_word_list.objectName() == "activeButton":
            self.current_active_button = self.btn_word_list
        elif self.btn_process.objectName() == "activeButton":
            self.current_active_button = self.btn_process
        elif self.btn_export.objectName() == "activeButton":
            self.current_active_button = self.btn_export

    def handle_display_click(self, event: QMouseEvent):
        if not self.video_widget.isVisible():
            self.open_file()

    def animate_console_loading(self):
        self.loading_console_dots = (self.loading_console_dots + 1) % 4
        dots = "." * self.loading_console_dots
        self.terminal.setText(f"Loading file{dots}")

    def generate_thumbnail(self, file_path):
        thumbnail_path = os.path.join(TEMP_DIR, "thumbnail.jpg")
        try:
            # Try a later timestamp to avoid black frames
            probe = ffmpeg.probe(file_path) # Use bundled ffprobe
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if video_stream:
                width = int(video_stream['width'])
                height = int(video_stream['height'])

                # Try at 5 seconds, fallback to 1 second if it fails
                try:
                    ffmpeg.input(file_path, ss="00:00:05").output(thumbnail_path, vframes=1, loglevel="error").run(overwrite_output=True) # Use bundled ffmpeg, loglevel error
                except ffmpeg.Error: # Specifically catch ffmpeg error for the first attempt
                    ffmpeg.input(file_path, ss="00:00:01").output(thumbnail_path, vframes=1, loglevel="error").run(overwrite_output=True) # Use bundled ffmpeg, loglevel error

                pixmap = QPixmap(thumbnail_path)
                if not pixmap.isNull():
                    self.display_frame.setPixmap(
                        pixmap.scaled(800, 450, Qt.AspectRatioMode.KeepAspectRatio, 
                                    Qt.TransformationMode.SmoothTransformation)
                    )
                    self.display_frame.setText("")
                    self.display_frame.setStyleSheet("")
                    self.temp_files.append(thumbnail_path)
                else: # pixmap.isNull()
                    self.display_frame.setPixmap(QPixmap())
                    self.display_frame.setText("Could not generate thumbnail (pixmap isNull).")
                    self.display_frame.setStyleSheet("font-size: 18px; color: #f44336; padding: 40px; background: #1e1e1e;")
        except ffmpeg.Error as e_ffmpeg:
            stderr_content = "N/A"
            if e_ffmpeg.stderr:
                try: stderr_content = e_ffmpeg.stderr.decode('utf-8', errors='replace')
                except Exception as decode_err: stderr_content = f"Error decoding stderr: {decode_err}"

            cmd_str = ' '.join(e_ffmpeg.cmd) if hasattr(e_ffmpeg, 'cmd') and e_ffmpeg.cmd else 'N/A'
            full_error_message = (f"FFmpeg Thumbnail Error:\n"
                                 f"CMD: {cmd_str}\n"
                                 f"STDOUT: {e_ffmpeg.stdout.decode('utf-8', errors='replace') if hasattr(e_ffmpeg, 'stdout') and e_ffmpeg.stdout else 'N/A'}\n"
                                 f"STDERR: {stderr_content}\n"
                                 f"Exception: {str(e_ffmpeg)}")
            print(full_error_message)

            if self.loading_console_timer:
                self.loading_console_timer.stop()
            self.terminal.setText(f"FFmpeg thumbnail error: {stderr_content.splitlines()[-1] if stderr_content != 'N/A' else str(e_ffmpeg)}")
            self.spinner.stop()
            self.display_frame.setPixmap(QPixmap())
            self.display_frame.setText(f"FFmpeg Error (Thumbnail):\n{stderr_content.splitlines()[-1] if stderr_content != 'N/A' else 'Could not generate thumbnail.'}")
            self.display_frame.setStyleSheet("font-size: 18px; color: #f44336; padding: 40px; background: #1e1e1e;")
        except Exception as e_generic:
            print(f"Generic thumbnail error: {type(e_generic).__name__}: {e_generic}")
            # ... (keep existing generic error handling or adapt as above) ...
            self.display_frame.setText(f"Error generating thumbnail:\n{type(e_generic).__name__}: {e_generic}")
            self.display_frame.setStyleSheet("font-size: 18px; color: #f44336; padding: 40px; background: #1e1e1e;")

    def on_scan_finished(self, scan_data, result_str):
        self.timestamps = scan_data['timestamps']
        self.all_timestamps = scan_data['all_timestamps']
        self._mute_segments = None  # Reset cached segments

        self.terminal.setText(result_str)
        self.show_post_scan_options()
        self.update_button_states()
        self.spinner.stop()
        self.spinner.hide()
        self.display_frame.show() # Show the thumbnail again

        # Re-enable buttons
        self.btn_process.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.btn_word_list.setEnabled(True)
        self.btn_export.setEnabled(True)

    def on_scan_error(self, error_msg):
        self.terminal.append(f"\nError during processing: {error_msg}")
        QMessageBox.critical(self, "Processing Error", f"Failed to process file: {error_msg}")
        self.spinner.stop()
        self.spinner.hide()
        # Re-enable buttons
        self.btn_process.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.btn_word_list.setEnabled(True)
        self.btn_export.setEnabled(True)

    def show_post_scan_options(self):
        self.post_scan_widget.show()

    def show_preview(self):
        if not self.current_file:
            return

        self.display_stack.setCurrentIndex(1) # Switch to the video player view
        self.controls_frame.show()
        self.preview_nav_widget.show()
        self.post_scan_widget.hide()

        print(f"DEBUG: show_preview() - START - for file: {self.current_file}")        
        # Explicitly disconnect the video output from any existing media player instance
        if hasattr(self, 'media_player') and self.media_player:
            print("DEBUG: show_preview() - Aggressively stopping and cleaning old player.")
            self.media_player.stop() # Explicit stop
            self.media_player.setSource(QUrl()) # Clear source
            self.media_player.setVideoOutput(None)
            self.media_player.setAudioOutput(None) # Ensure audio output is also cleared
            QApplication.processEvents() # Process stop/clear

            # Explicitly schedule old objects for deletion
            print("DEBUG: show_preview() - Scheduling old media_player and audio_output for deletion and clearing references.")
            if self.media_player: # Check again before deleteLater
                self.media_player.deleteLater()
                self.media_player = None # Clear the reference
            if hasattr(self, 'audio_output') and self.audio_output: # Check audio_output too
                self.audio_output.deleteLater()
                self.audio_output = None # Clear the reference
        QApplication.processEvents() # Allow the deletion scheduling to be processed

        # Defer the initialization of the new player and setting the source
        # Reduced delay
        QTimer.singleShot(50, self._deferred_player_init_and_play) 
        print(f"DEBUG: show_preview() - QTimer for _deferred_player_init_and_play set with 50ms delay.")

    def _set_new_media_source_and_play(self, file_path):
        print(f"DEBUG: _set_new_media_source_and_play() - Setting media source to: {file_path}")
        try:
            # Ensure media_player is valid after _initialize_media_player
            if not hasattr(self, 'media_player') or not self.media_player:
                print("DEBUG: _set_new_media_source_and_play() - media_player is not initialized!")
                return
            # Ensure video_widget is also valid and connected
            if not self.video_widget:
                print("DEBUG: _set_new_media_source_and_play() - video_widget is not initialized!")
                return
            if self.media_player.videoOutput() != self.video_widget: # Check if it's actually connected
                print("DEBUG: _set_new_media_source_and_play() - video_widget not connected to media_player. Re-connecting.")
                self.media_player.setVideoOutput(self.video_widget) # Attempt to reconnect
            self.media_player.setSource(QUrl.fromLocalFile(file_path))
            print("DEBUG: _set_new_media_source_and_play() - media_player.setSource() called successfully.")
            QApplication.processEvents() # Process events after setting new source
            print("DEBUG: _set_new_media_source_and_play() - QApplication.processEvents() after setSource. Setting QTimer for playback.")
            # Reduced delay
            QTimer.singleShot(100, self._start_preview_playback) 
            print("DEBUG: _set_new_media_source_and_play() - QTimer for _start_preview_playback set with 100ms delay.")
        except Exception as e:
            print(f"DEBUG: _set_new_media_source_and_play() - Error setting media source or starting playback timer: {e}")

    def _deferred_player_init_and_play(self):
        print("DEBUG: _deferred_player_init_and_play() - START")
        QApplication.processEvents() # Extra process events before initializing
        self._initialize_media_player() # This will re-create self.media_player and self.audio_output
        QApplication.processEvents() # Allow new player to be fully set up
        try:
            # Pass self.current_file to the method that sets the source and starts playback
            self._set_new_media_source_and_play(self.current_file)
        except Exception as e:
            print(f"DEBUG: _deferred_player_init_and_play() - Error calling _set_new_media_source_and_play: {e}")


    def _start_preview_playback(self):
        print("DEBUG: _start_preview_playback() called. Attempting to play.")
        self.media_player.play()
        self.btn_play.setText("⏸")
        self.update_button_states()

    def toggle_play(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.btn_play.setText("▶")
        else:
            self.media_player.play()
            self.btn_play.setText("⏸")

    def update_progress(self, position):
        duration = self.media_player.duration()
        if duration > 0:
            self.timeline.update_position(position / 1000)
            
            seconds = position / 1000
            minutes = int(seconds // 60)
            seconds = seconds % 60
            self.time_label.setText(
                f"{minutes:02d}:{seconds:06.3f}"
            )

    def update_duration(self, duration):
        if duration > 0:
            self.timeline.duration = duration / 1000
            self.timeline.timestamps = self.all_timestamps
            self.timeline.draw_time_markers()
            self.timeline.draw_word_markers()

    def next_timestamp(self):
        if not self.all_timestamps:
            return

        current_pos = self.media_player.position() / 1000
        next_time = min([t for t in self.all_timestamps if t > current_pos], default=None)
        if next_time:
            self.media_player.setPosition(int(next_time * 1000))

    def prev_timestamp(self):
        if not self.all_timestamps:
            return

        current_pos = self.media_player.position() / 1000
        prev_time = max([t for t in self.all_timestamps if t < current_pos], default=None)
        if prev_time:
            self.media_player.setPosition(int(prev_time * 1000))

    def set_playback_speed(self, speed_text):
        speed = float(speed_text[:-1])
        self.media_player.setPlaybackRate(speed)

    def set_volume(self, volume):
        self.audio_output.setVolume(volume / 100)

    def get_mute_segments(self):
        """Returns sorted list of (start, end) segments to mute"""
        if self._mute_segments is None:
            segments = []
            for word, times in self.timestamps.items():
                for start, end in times:
                    # Optionally add a tiny buffer if you want (e.g., -0.02, +0.02)
                    segments.append((max(0, start-0.02), end+0.02))
            # Merge overlapping segments
            segments.sort()
            merged = []
            for seg in segments:
                if not merged:
                    merged.append(list(seg))
                else:
                    last = merged[-1]
                    if seg[0] <= last[1]:
                        last[1] = max(last[1], seg[1])
                    else:
                        merged.append(list(seg))
            self._mute_segments = merged
        return self._mute_segments

    def mute_words(self):
        if not self.current_file or not self.timestamps:
            return

        self.media_player.stop()

        base, ext = os.path.splitext(self.current_file)
        output_file = os.path.join(TEMP_DIR, f"{os.path.splitext(os.path.basename(base))[0]}_censored{ext}")

        progress = QProgressDialog("Processing video...", None, 0, 100, self)
        progress.setWindowTitle("Processing")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.show()

        try:
            probe = ffmpeg.probe(self.current_file) # Use globally set FFPROBE_PATH
            audio_info = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
            total_duration = float(audio_info['duration'])
            mute_segments = self.get_mute_segments()
            print("Mute segments:", mute_segments)  # Debug

            input_stream = ffmpeg.input(self.current_file)

            if self.selected_sound == "Mute":
                audio = input_stream.audio
                for start, end in mute_segments:
                    audio = audio.filter('volume', volume=0, enable=f'between(t,{start},{end})')

                progress.setValue(50)
                QApplication.processEvents()

                (
                    ffmpeg.output(
                        input_stream.video,
                        audio,
                        output_file,
                        vcodec='libx264',
                        pix_fmt='yuv420p',
                        acodec='aac',
                        level='3.1'  # Explicitly set H.264 level
                    )
                    .run(quiet=False, overwrite_output=True) # Use globally set FFMPEG_PATH, quiet=False
                )
            else:
                sound_file = self.sound_replacements[self.selected_sound]
                if not os.path.exists(sound_file):
                    raise FileNotFoundError(f"Sound file {sound_file} not found")

                audio_stream = input_stream.audio
                input_sound = ffmpeg.input(sound_file)
                mute_count = len(mute_segments)

                if mute_count > 0:
                    split_streams = input_sound.audio.filter_multi_output('asplit', mute_count)
                else:
                    split_streams = []

                audio_segments = []
                last_end = 0

                for idx, (start, end) in enumerate(mute_segments):
                    if start > last_end:
                        before = audio_stream.filter('atrim', start=last_end, end=start).filter('asetpts', 'N/SR/TB')
                        audio_segments.append(before)
                    duration = end - start
                    # Loop the sound to cover the whole segment
                    sound = (
                        split_streams[idx]
                        .filter('aloop', loop=-1, size=2147483647)
                        .filter('atrim', start=0, end=duration)
                        .filter('asetpts', 'N/SR/TB')
                    )
                    audio_segments.append(sound)
                    last_end = end

                if last_end < total_duration:
                    after = audio_stream.filter('atrim', start=last_end).filter('asetpts', 'N/SR/TB')
                    audio_segments.append(after)

                if len(audio_segments) > 1:
                    audio_out = ffmpeg.concat(*audio_segments, v=0, a=1)
                else:
                    audio_out = audio_segments[0]

                progress.setValue(50)
                QApplication.processEvents()

                (
                    ffmpeg.output(
                        input_stream.video,
                        audio_out,
                        output_file,
                        vcodec='libx264',
                        pix_fmt='yuv420p',
                        acodec='aac',
                        level='3.1'  # Explicitly set H.264 level
                    ) # loglevel defaults to 'info' which can be verbose; use 'error' for less output unless debugging ffmpeg itself
                    .run(quiet=False, overwrite_output=True) # Use globally set FFMPEG_PATH, quiet=False
                )

            # Check output file
            if not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
                raise Exception("FFmpeg did not produce an output file.")

            self.current_file = output_file
            self.temp_files.append(output_file)
            self.processing_complete = True
            
            progress.close()
            QApplication.processEvents() # Allow dialog to fully close

            QMessageBox.information(self, "Success", "Processing completed!")
            
            # Update button states, this will enable the main Export button
            self.update_button_states()

            # Revert UI to show original thumbnail and hide preview controls, ready for export
            self.display_stack.setCurrentIndex(0) 
            self.controls_frame.hide()
            self.preview_nav_widget.hide() 
            self.post_scan_widget.hide() # Ensure this is hidden too
            self.statusBar().showMessage("Processing complete. Ready to export.", 5000)

        except ffmpeg.Error as e:
            progress.close()
            QApplication.processEvents()
            QMessageBox.critical(self, "FFmpeg Error", f"FFmpeg error: {e.stderr.decode('utf-8')}")
        except Exception as e:
            progress.close()
            QApplication.processEvents()
            QMessageBox.critical(self, "Error", f"Failed to process words: {str(e)}")
    def export_file(self):
        if not self.current_file:
            return

        # Do NOT clean up temp files before exporting!
        # self.cleanup_temp_files()

        default_name = os.path.basename(self.current_file)
        file_name, _ = QFileDialog.getSaveFileName(
            self, "Save File", default_name, "Video Files (*.mp4);;All Files (*)")

        if file_name:
            try:
                if not file_name.lower().endswith('.mp4'):
                    file_name += '.mp4'
                import shutil
                shutil.copy2(self.current_file, file_name)
                QMessageBox.information(self, "Export Complete", "File exported successfully!")
                self.reset_ui()
                self.cleanup_temp_files()
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export file: {str(e)}\n\nYour processed file might still be in the temp folder: {self.current_file}")
                # Don't reset UI or cleanup if export fails, so user can retry or find temp file
    def cleanup_temp_files(self):
        # Stop and clear the media player before cleaning up files it might be using
        """Delete all files in the temp folder.""" # Docstring moved to the correct position
        print("DEBUG: cleanup_temp_files() - START")
        try:
            # Check state before stopping to avoid potential issues
            if self.media_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
                 self.media_player.stop()
            self.media_player.setSource(QUrl()) # Clear source after stopping
        except Exception as e:
            print(f"Error stopping media player during cleanup: {e}")


        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}: {e}")
        print("DEBUG: cleanup_temp_files() - END")
        self.temp_files = []
    
    def handle_media_player_error(self, error, error_string):
        print(f"QMediaPlayer Error: {error} - {error_string}")
        # Optionally show a message box to the user

    def handle_media_status_changed(self, status):
        print(f"DEBUG: QMediaPlayer MediaStatusChanged: {status}")
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            print(f"DEBUG: MediaStatus is InvalidMedia. Player Error: {self.media_player.errorString()}")

    def handle_playback_state_changed(self, state):
        print(f"DEBUG: QMediaPlayer PlaybackStateChanged: {state}")

    def _initialize_media_player(self):
        print("DEBUG: _initialize_media_player() called")
        # Defensive cleanup: If old ones exist and weren't properly cleaned, try to delete them again.
        if hasattr(self, 'media_player') and self.media_player:
            print("DEBUG: _initialize_media_player() - Found existing media_player, scheduling for deletion.")
            self.media_player.setVideoOutput(None) # Disconnect first
            self.media_player.setAudioOutput(None)
            self.media_player.deleteLater()
        if hasattr(self, 'audio_output') and self.audio_output:
            print("DEBUG: _initialize_media_player() - Found existing audio_output, scheduling for deletion.")
            self.audio_output.deleteLater()

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput() # Recreate QAudioOutput as well
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(self.handle_media_player_error)
        self.media_player.mediaStatusChanged.connect(self.handle_media_status_changed)
        self.media_player.playbackStateChanged.connect(self.handle_playback_state_changed)
        self.media_player.positionChanged.connect(self.update_progress)
        self.media_player.durationChanged.connect(self.update_duration)
        self.media_player.setVideoOutput(self.video_widget)
        print(f"DEBUG: New QMediaPlayer instance: {self.media_player}")

    def reset_ui(self):
         # Stop and clear the media player
        print("DEBUG: reset_ui() - START")
        if hasattr(self, 'media_player') and self.media_player:
            print("DEBUG: reset_ui() - Stopping and cleaning up old media player.")
            self.media_player.stop()
            self.media_player.setVideoOutput(None) # Disconnect video output
            self.media_player.setAudioOutput(None) # Disconnect audio output
            if self.media_player: # Check before deleteLater
                self.media_player.deleteLater() 
            if hasattr(self, 'audio_output') and self.audio_output:
                self.audio_output.deleteLater() 
            self.media_player = None # Clear reference
            self.audio_output = None # Clear reference
        
        self.cleanup_temp_files() # Clean up temp files *before* initializing new player (this already has try-except for player ops)

        QApplication.processEvents() # Process events to ensure player state is updated
        self.display_stack.setCurrentIndex(0) # Show the initial display frame
        self.preview_nav_widget.hide()
        self.post_scan_widget.hide()
        self.controls_frame.hide() # Explicitly hide controls_frame
        self.display_frame.show()
        self.display_frame.setText("Click to add file or drag file here")
        self.display_frame.setStyleSheet("""
            font-size: 24px; 
            color: #777;
            padding: 40px;
        """)
        self.terminal.clear()
        self.current_file = None
        self.timestamps = {}
        self.all_timestamps = []
        self._mute_segments = None
        self.processing_complete = False
        self.btn_export.setEnabled(False)
        self.selected_sound = "Mute" # Reset sound selection
        
        self._initialize_media_player() # Create new instances *after* cleanup
        
        # Reset confirm button if it was changed
        self.btn_confirm.setText("Confirm and Continue →")
        self.btn_confirm.disconnect()
        self.btn_confirm.clicked.connect(self.mute_words)
        
        self.update_button_states()

    def edit_words(self):
        dialog = WordListDialog(self.word_list, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.word_list = dialog.word_list
            self.current_template = dialog.current_template
            self.save_settings()
        # Remove active/nextStep status from all nav buttons
        self.btn_open.setObjectName("")
        self.btn_word_list.setObjectName("")
        self.btn_process.setObjectName("")
        self.btn_export.setObjectName("")
        # Set only Begin Scan as next step
        self.current_active_button = self.btn_process
        self.btn_process.setObjectName("nextStepButton")
        self.update_button_states()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.cleanup_temp_files()
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(('.mp4', '.avi', '.mov')):
                # self.display_stack.setCurrentWidget(self.spinner) # display_stack is not used anymore (already fixed)
                self.display_stack.setCurrentIndex(0) # Ensure we are on the thumbnail/initial view
                self.spinner.show()
                self.spinner.start()
                self.terminal.setText("Loading file")
                self.loading_console_dots = 0
                if self.loading_console_timer is None:
                    self.loading_console_timer = QTimer(self)
                    self.loading_console_timer.timeout.connect(self.animate_console_loading)
                self.loading_console_timer.start(400)
                QApplication.processEvents()
                self.load_file(file_path)
                self.update_button_states()
                break

    def closeEvent(self, event):
        # Clean up temp files when closing
        self.cleanup_temp_files()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Auto-login if user_data.json exists and is valid
    auto_login = False
    if os.path.exists("user_data.json"):
        try:
            with open("user_data.json", "r") as f:
                user_data = json.load(f)
            expires = datetime.strptime(user_data["expires"], "%Y-%m-%d")
            if datetime.now() <= expires:
                auto_login = True
        except Exception as e:
            print(f"Auto-login check failed: {e}")

    if auto_login:
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    else:
        license_dialog = LicenseDialog()
        if license_dialog.exec() == QDialog.DialogCode.Accepted:
            window = MainWindow()
            window.show()
            sys.exit(app.exec())
        else:
            sys.exit(0)