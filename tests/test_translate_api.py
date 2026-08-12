import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core import translate_api


class TranslateApiImageTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.test_image_path = cls.project_root / "test.png"
        if not cls.test_image_path.exists():
            raise FileNotFoundError(f"Missing test image: {cls.test_image_path}")

    def make_config(self):
        return {
            "ocr_provider": "baidu",
            "translation_provider": "deepseek",
            "baidu_api_key": "ocr-key",
            "baidu_secret_key": "ocr-secret",
            "baidu_translate_appid": "",
            "baidu_translate_appkey": "",
            "deepseek_api_key": "deepseek-key",
            "deeplx_endpoint": "",
            "translate_language": "English",
        }

    def make_ocr_results(self):
        return [
            {
                "words": "Hello world",
                "location": {
                    "left": 32,
                    "top": 48,
                    "width": 220,
                    "height": 44,
                },
            }
        ]

    def make_paragraphs(self):
        return [
            {
                "words": "Hello world",
                "direction": "horizontal",
                "res": self.make_ocr_results(),
            }
        ]

    def save_translated_image(self, image, output_path, paragraphs, translations,
                              debug_output_path=None, skip_background_fill=False,
                              original_image=None, **kwargs):
        image.copy().save(output_path)
        return True

    def test_process_image_task_uses_test_png_and_writes_outputs(self):
        config = self.make_config()
        progress_events = []
        with Image.open(self.test_image_path) as image:
            expected_size = image.size

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with (
                patch("core.translate_api.get_baidu_ocr_token", return_value="token"),
                patch("core.translate_api.baidu_ocr_with_location", return_value=self.make_ocr_results()),
                patch("core.translate_api.text_process.merge_text_lines", return_value=self.make_paragraphs()),
                patch("core.translate_api.parallel_translate", return_value=["Bonjour le monde"]),
                patch(
                    "core.translate_api.text_process.replace_text_in_image",
                    side_effect=self.save_translated_image,
                ) as replace_mock,
            ):
                result = translate_api.process_image_task(
                    self.test_image_path,
                    config,
                    output_dir=output_dir,
                    progress_callback=lambda index, name: progress_events.append((index, name)),
                )

            output_image_path = Path(result["output_path"])
            output_text_path = Path(result["text_output_path"])

            self.assertTrue(result["success"], result["error"])
            self.assertEqual(result["ocr_region_count"], 1)
            self.assertEqual(result["paragraph_count"], 1)
            self.assertEqual([event[0] for event in progress_events], [1, 2, 3, 4, 5])
            self.assertTrue(output_image_path.exists())
            self.assertTrue(output_text_path.exists())
            self.assertIn("Hello world", output_text_path.read_text(encoding="utf-8"))
            self.assertIn("Bonjour le monde", output_text_path.read_text(encoding="utf-8"))

            with Image.open(output_image_path) as translated_image:
                self.assertEqual(translated_image.size, expected_size)

            replace_image = replace_mock.call_args.args[0]
            self.assertEqual(replace_image.size, expected_size)

    def test_process_image_task_without_detected_text_copies_test_png(self):
        config = self.make_config()
        progress_events = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with (
                patch("core.translate_api.get_baidu_ocr_token", return_value="token"),
                patch("core.translate_api.baidu_ocr_with_location", return_value=[]),
            ):
                result = translate_api.process_image_task(
                    self.test_image_path,
                    config,
                    output_dir=output_dir,
                    progress_callback=lambda index, name: progress_events.append((index, name)),
                )

            output_image_path = Path(result["output_path"])
            output_text_path = Path(result["text_output_path"])

            with Image.open(self.test_image_path) as original_image, Image.open(output_image_path) as output_image:
                self.assertEqual(output_image.size, original_image.size)
                self.assertEqual(output_image.mode, original_image.mode)
                self.assertEqual(output_image.tobytes(), original_image.tobytes())

            text_output = output_text_path.read_text(encoding="utf-8")

        self.assertTrue(result["success"], result["error"])
        self.assertEqual(result["ocr_region_count"], 0)
        self.assertEqual(result["paragraph_count"], 0)
        self.assertEqual([event[0] for event in progress_events], [1, 2, 3, 4, 5])
        self.assertEqual(text_output.strip(), "原始文本:\n\n\n翻译结果:")

    def test_process_pil_image_task_uses_test_png_and_saves_source_image(self):
        config = self.make_config()
        progress_events = []

        with Image.open(self.test_image_path) as source_image:
            test_image = source_image.copy()
            expected_size = test_image.size

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            with (
                patch("core.translate_api.get_baidu_ocr_token", return_value="token"),
                patch("core.translate_api.baidu_ocr_image_with_location", return_value=self.make_ocr_results()),
                patch("core.translate_api.text_process.merge_text_lines", return_value=self.make_paragraphs()),
                patch("core.translate_api.parallel_translate", return_value=["Hola mundo"]),
                patch(
                    "core.translate_api.text_process.replace_text_in_image",
                    side_effect=self.save_translated_image,
                ),
            ):
                result = translate_api.process_pil_image_task(
                    test_image,
                    config,
                    output_dir=output_dir,
                    output_base_name="memory_test",
                    progress_callback=lambda index, name: progress_events.append((index, name)),
                    image_name="memory_test",
                )

            output_image_path = Path(result["output_path"])
            output_text_path = Path(result["text_output_path"])
            source_output_path = Path(result["source_output_path"])

            with Image.open(output_image_path) as output_image, Image.open(source_output_path) as source_output_image:
                self.assertEqual(output_image.size, expected_size)
                self.assertEqual(source_output_image.size, expected_size)

            text_output = output_text_path.read_text(encoding="utf-8")

        self.assertTrue(result["success"], result["error"])
        self.assertEqual(result["image_path"], "memory_test")
        self.assertEqual(result["ocr_region_count"], 1)
        self.assertEqual(result["paragraph_count"], 1)
        self.assertEqual([event[0] for event in progress_events], [1, 2, 3, 4, 5])
        self.assertIn("Hello world", text_output)
        self.assertIn("Hola mundo", text_output)


if __name__ == "__main__":
    unittest.main()
