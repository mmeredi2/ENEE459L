import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw
import warnings
from scipy.ndimage import convolve, gaussian_filter

MODEL_PATH = "version-RFB-320.onnx"

warnings.filterwarnings("ignore", category=UserWarning)

sess_options = ort.SessionOptions()
sess_options.log_severity_level = 3  

# 3. Use only available providers to prevent the provider fallback warning
desired_providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
available_providers = [p for p in desired_providers if p in ort.get_available_providers()]

# face detection
def hard_nms(box_scores, iou_threshold, top_k=-1, candidate_size=200):
    boxes = box_scores[:, :4]
    scores = box_scores[:, 4]

    ordered = np.argsort(scores)
    ordered = ordered[-candidate_size:]

    picked = []
    while len(ordered) > 0:
        picked.append(ordered[-1])

        if (len(picked) >= top_k and top_k > 0) or len(ordered) == 1:
            break

        rest = ordered[:-1]

        x1_act, y1_act, x2_act, y2_act = boxes[ordered[-1]]
        area_act = max(0.0, x2_act - x1_act) * max(0.0, y2_act - y1_act)

        x1_rem = boxes[rest, 0]
        y1_rem = boxes[rest, 1]
        x2_rem = boxes[rest, 2]
        y2_rem = boxes[rest, 3]
        area_rem = np.maximum(0.0, x2_rem - x1_rem) * np.maximum(0.0, y2_rem - y1_rem)

        x1_max = np.maximum(x1_act, x1_rem)
        y1_max = np.maximum(y1_act, y1_rem)
        x2_min = np.minimum(x2_act, x2_rem)
        y2_min = np.minimum(y2_act, y2_rem)

        intersection = np.maximum(0.0, x2_min - x1_max) * np.maximum(0.0, y2_min - y1_max)

        union = area_act + area_rem - intersection
        iou = intersection / union
        ordered = rest[np.where(iou <= iou_threshold)[0]]

    return box_scores[picked]

def detect_faces(image_path, output_path="output_detected.png", conf_threshold=0.7):
    image = Image.open(image_path).convert("RGB")
    w, h = image.size

    input_image = image.resize((320, 240))
    input_image = np.array(input_image).astype(np.float32)
    input_image = (input_image - 127.0) / 128.0
    input_image = np.transpose(input_image, (2, 0, 1))
    input_image = np.expand_dims(input_image, axis=0)

    session = ort.InferenceSession(MODEL_PATH, sess_options=sess_options, providers=available_providers)
    outputs = session.run(None, {session.get_inputs()[0].name: input_image})

    boxes = outputs[1].squeeze()
    scores = outputs[0].squeeze()
    face_score = scores[:, 1]
    mask = face_score > conf_threshold
    boxes = boxes[mask]
    face_score = face_score[mask]

    if len(face_score) == 0:
        image.save(output_path)
        return

    box_scores = np.hstack((boxes, face_score[:, np.newaxis]))
    nms_boxes = hard_nms(box_scores, iou_threshold=0.3)

    draw = ImageDraw.Draw(image)
    for box in nms_boxes:
        x1 = box[0] * w
        y1 = box[1] * h
        x2 = box[2] * w
        y2 = box[3] * h
        score = box[4]
        draw.rectangle([x1, y1, x2, y2], outline="red", width=2)
        draw.text((x1, y1), f"{score:.2f}", fill="red")

    image.save(output_path)

# Edge detection
def non_maximum_suppression(magnitude, angle):
    output = np.zeros(magnitude.shape, dtype=np.float32)
    angle_deg = np.rad2deg(angle) % 180

    for i in range(1, magnitude.shape[0] - 1):
        for j in range(1, magnitude.shape[1] - 1):
            if (0 <= angle_deg[i, j] < 22.5) or (157.5 <= angle_deg[i, j] <= 180):
                q = magnitude[i, j + 1]
                r = magnitude[i, j - 1]
            elif (22.5 <= angle_deg[i, j] < 67.5):
                q = magnitude[i + 1, j - 1]
                r = magnitude[i - 1, j + 1]
            elif (67.5 <= angle_deg[i, j] < 112.5):
                q = magnitude[i + 1, j]
                r = magnitude[i - 1, j]
            elif (112.5 <= angle_deg[i, j] < 157.5):
                q = magnitude[i - 1, j - 1]
                r = magnitude[i + 1, j + 1]

            if (magnitude[i, j] >= q) and (magnitude[i, j] >= r):
                output[i, j] = magnitude[i, j]
            else:
                output[i, j] = 0

    return output

def hysteresis_thresholding(img, low_thresh, high_thresh):
    strong = 255
    weak = 50
    suppressed = 0

    output = np.zeros(img.shape, dtype=np.uint8)
    output[img >= high_thresh] = strong
    output[(img >= low_thresh) & (img < high_thresh)] = weak

    for i in range(1, img.shape[0] - 1):
            for j in range(1, img.shape[1] - 1):
                if output[i, j] == weak:
                    patch = output[i - 1:i + 2, j - 1:j + 2]
                    if np.any(patch == strong):
                        output[i, j] = strong
                    else:
                        output[i, j] = 0

    output[output == weak] = 0

    return output

def canny_scipy(image_path, output_path="edges_scipy.png", low=20, high=60):
    image = Image.open(image_path).convert("L")
    image_np = np.array(image, dtype=np.float32)
    smoothed = gaussian_filter(image_np, sigma=1.4)

    Kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])
    Ky = np.array([[1, 2, 1], [0, 0, 0], [-1, -2, -1]])

    Ix = convolve(smoothed, Kx)
    Iy = convolve(smoothed, Ky)

    magnitude = np.hypot(Ix, Iy)
    max_magnitude = np.max(magnitude)
    if max_magnitude > 0:
        magnitude = (magnitude / max_magnitude) * 255.0
    angle = np.arctan2(Iy, Ix)

    nms_output = non_maximum_suppression(magnitude, angle)

    edges = hysteresis_thresholding(nms_output, low_thresh=low, high_thresh=high)
    edges_image = Image.fromarray(edges)
    edges_image.save(output_path)

if __name__ == "__main__":
    detect_faces("face.jpg")
    canny_scipy("face.jpg")