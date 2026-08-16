"""OCR 解析器测试：注入假引擎验证流程，不依赖真实模型下载。"""

from src.parsers.ocr_parser import OcrParser


class _FakeEngine:
    """返回固定识别结果 [[box, text, score], ...]，模拟 rapidocr_onnxruntime 输出。"""

    def __call__(self, path):
        return [
            ([[0, 0, 100, 20]], "本产品保本保收益", 0.95),
            ([[0, 30, 120, 50]], "预期年化收益率5.8%", 0.92),
        ], 0.5


def test_ocr_parser_blocks(tmp_path):
    p = tmp_path / "poster.png"
    p.write_bytes(b"\x89PNG fake")  # 内容不实际解码
    parser = OcrParser(engine=_FakeEngine())
    doc = parser.parse(str(p))
    assert len(doc.blocks) == 2
    assert doc.blocks[0].text == "本产品保本保收益"
    assert doc.blocks[0].page == 1
    assert doc.blocks[1].paragraph == 2
    assert doc.blocks[0].heading is False


def test_ocr_parser_empty_result(tmp_path):
    class _Empty:
        def __call__(self, path):
            return [], 0.0

    p = tmp_path / "blank.png"
    p.write_bytes(b"\x89PNG fake")
    parser = OcrParser(engine=_Empty())
    doc = parser.parse(str(p))
    assert doc.blocks == []
