/**
 * services/imageUtils.ts — Image preparation utilities for the grading API.
 *
 * The grading endpoint expects a raw base64 string with no data URI prefix.
 * This module normalises any image source into that format.
 */

// Matches "data:image/jpeg;base64," or any similar data URI prefix.
const DATA_URI_PREFIX_RE = /^data:[^;]+;base64,/;

/**
 * Read a local file URI into base64 using fetch + FileReader.
 * Both APIs are available in React Native's JavaScriptCore runtime.
 */
function readFileAsBase64(uri: string): Promise<string> {
  return fetch(uri)
    .then((response) => response.blob())
    .then(
      (blob) =>
        new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => {
            const result = reader.result;
            if (typeof result !== "string") {
              reject(new Error("FileReader did not return a string"));
              return;
            }
            // readAsDataURL always produces a data URI — strip the prefix.
            resolve(result.replace(DATA_URI_PREFIX_RE, ""));
          };
          reader.onerror = () =>
            reject(new Error("Failed to read image file as base64"));
          reader.readAsDataURL(blob);
        })
    );
}

/**
 * Prepare an image for upload to the grading API.
 *
 * Accepts either:
 *  - A local file URI from expo-image-picker (e.g. "file:///var/…/image.jpg")
 *  - A data URI (e.g. "data:image/jpeg;base64,/9j/4AA…")
 *
 * In all cases the return value is a raw base64 string with no prefix,
 * suitable for the `image_base64` field of a GradeRequest.
 *
 * Note: when using expo-image-picker with `base64: true`, prefer reading
 * `result.assets[0].base64` directly (already raw base64) over passing the
 * URI here, as it avoids a redundant file read.
 *
 * @param uri - Image URI from expo-image-picker or a data URI string.
 * @returns   Raw base64 string (no "data:…;base64," prefix).
 * @throws    Error if the file cannot be read.
 */
export async function prepareImageForUpload(uri: string): Promise<string> {
  // Data URI — strip the prefix and return the base64 payload directly.
  if (DATA_URI_PREFIX_RE.test(uri)) {
    return uri.replace(DATA_URI_PREFIX_RE, "");
  }

  // Local file URI — read via fetch + FileReader.
  return readFileAsBase64(uri);
}
