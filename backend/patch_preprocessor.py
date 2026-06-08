import sys, re

with open('app/ocr/preprocessor.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'    variants: Dict\[str, np\.ndarray\] = \{.*?"deskewed":      deskewed,\n    \}'

replacement = '''    variants: Dict[str, np.ndarray] = {
        "grayscale":     gray,
    }

    # Adaptive Preprocessing Selection
    # Calculate sharpness (variance of Laplacian)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    # If image is very sharp, we don't need heavy processing
    if laplacian_var > 1500:
        logger.debug("[preprocessor] Image is highly sharp (%.2f). Using minimal variants.", laplacian_var)
        variants["denoised"] = denoised
    elif laplacian_var < 300:
        logger.debug("[preprocessor] Image is blurry (%.2f). Using high contrast and sharpening.", laplacian_var)
        variants["sharpened"] = sharpened
        variants["high_contrast"] = hi_contrast
        variants["clahe"] = clahe
    else:
        logger.debug("[preprocessor] Image has moderate sharpness (%.2f). Using balanced variants.", laplacian_var)
        variants["denoised"] = denoised
        variants["clahe"] = clahe
        variants["sharpened"] = sharpened

    # Always include deskewed if it made a difference
    if not np.array_equal(deskewed, clahe) and not np.array_equal(deskewed, gray):
        variants["deskewed"] = deskewed'''

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

if new_content == content:
    print('Failed to replace.')
else:
    with open('app/ocr/preprocessor.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Successfully updated preprocessor adaptive selection.')
