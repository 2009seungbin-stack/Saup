"""Real canvas files: decode downloaded PNG/ZIP, replay editable projects."""
import json
import struct
import zlib
import zipfile
from playwright.sync_api import expect


def sample_png():
    # Synthetic two-color product-photo stand-in; no external images needed.
    def chunk(kind, data):
        return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))
    width,height=240,160
    rows=b''.join(b'\0'+b''.join(bytes((37,106,83) if 60<x<180 and 30<y<130 else (240,233,219)) for x in range(width)) for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b'')


def test_creative_render_download_and_restore(pages,tmp_path):
    page=pages('operator');page.get_by_role('button',name='상품 제작',exact=True).click()
    generate=page.get_by_role('button',name='상세페이지·섬네일 자동 생성',exact=True)
    expect(generate).to_be_disabled()
    page.get_by_label('상품명',exact=True).fill('테스트 세라믹 컵 <script>')
    page.get_by_label('한 줄 소개',exact=True).fill('실제 제공된 상품 정보')
    page.get_by_label('상품 정보',exact=True).fill('소재: 세라믹\n구성: 컵 1개')
    page.get_by_label('상세 설명',exact=True).fill('줄바꿈과 긴 설명을 자동 배치합니다. '*45)
    page.get_by_label('상품 사진 추가',exact=True).set_input_files({'name':'sample.png','mimeType':'image/png','buffer':sample_png()})
    expect(page.get_by_alt_text('상품 사진 1',exact=True)).to_be_visible()
    page.get_by_label('섬네일 크기',exact=True).select_option('800')
    generate.click();expect(page.get_by_role('status')).to_contain_text('섬네일 3개',timeout=30000)
    with page.expect_download() as event:page.get_by_role('button',name='전체 ZIP 다운로드',exact=True).click()
    target=tmp_path/'assets.zip';event.value.save_as(target)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={'thumbnail-clean.png','thumbnail-title.png','thumbnail-card.png','detail.png','detail.html','saup-creative-project.json','README.txt'}
        for name in ['thumbnail-clean.png','thumbnail-title.png','thumbnail-card.png']:
            data=archive.read(name);assert data[:8]==b'\x89PNG\r\n\x1a\n'
            assert struct.unpack('>II',data[16:24])==(800,800)
        width,height=struct.unpack('>II',archive.read('detail.png')[16:24]);assert width==860 and 1800<height<14000
        html=archive.read('detail.html').decode();assert '&lt;script&gt;' in html and '<script>' not in html
        project=archive.read('saup-creative-project.json');assert len(json.loads(project)['photos'])==1
        # Keep locally decoded results for image inspection without recompression.
        for name in ['detail.png','thumbnail-title.png']: (tmp_path/name).write_bytes(archive.read(name))
    page.get_by_label('상품명',exact=True).fill('변경된 이름')
    expect(page.get_by_role('button',name='전체 ZIP 다운로드',exact=True)).to_be_disabled()
    page.on('dialog',lambda dialog:dialog.accept())
    page.get_by_label('편집 파일 열기',exact=True).set_input_files({'name':'project.json','mimeType':'application/json','buffer':project})
    expect(page.get_by_label('상품명',exact=True)).to_have_value('테스트 세라믹 컵 <script>')
    page.get_by_role('button',name='상품',exact=True).click();page.get_by_role('button',name='상품 제작',exact=True).click()
    expect(page.get_by_label('상품명',exact=True)).to_have_value('테스트 세라믹 컵 <script>')
    generate.click();expect(page.get_by_role('button',name='전체 ZIP 다운로드',exact=True)).to_be_enabled(timeout=30000)
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('section[aria-label="제작 결과 미리보기"]').evaluate('(el)=>el.getBoundingClientRect().right')<=390


def test_creative_rejects_invalid_files_and_viewer(pages):
    page=pages('operator');page.get_by_role('button',name='상품 제작',exact=True).click()
    page.get_by_label('상품 사진 추가',exact=True).set_input_files({'name':'bad.svg','mimeType':'image/svg+xml','buffer':b'<svg/>'})
    expect(page.get_by_role('alert').filter(has_text='JPG')).to_be_visible()
    page.get_by_label('편집 파일 열기',exact=True).set_input_files({'name':'bad.json','mimeType':'application/json','buffer':b'{"version":99}'})
    expect(page.get_by_role('alert').filter(has_text='지원하지 않는')).to_be_visible()
    viewer=pages('viewer');viewer.get_by_role('button',name='상품 제작',exact=True).click()
    expect(viewer.get_by_text('상세페이지·섬네일 제작은 운영자 또는 관리자 계정으로 이용할 수 있습니다.')).to_be_visible()
    expect(viewer.get_by_label('상품 사진 추가',exact=True)).to_have_count(0)
