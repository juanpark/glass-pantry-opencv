import os

# Refuse to decode images over 50 megapixels (OpenCV's own default is about a gigapixel, far beyond the memory
# this service has). Must be set before cv2 is first imported.
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(50_000_000))
