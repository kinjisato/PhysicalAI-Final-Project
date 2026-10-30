"""Ubuntu terminal input for simulation-only requests; core motion logic unchanged."""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from simulation_cli import validate_input

def main():
    print('Physical AI / CRANE+ simulation', flush=True)
    print('RVizでロボットを確認してから日本語指示を入力してください。', flush=True)
    print('例: 青、黄、緑の順番に近づいて', flush=True)
    print('終了: exit   注意: 実機接続は禁止', flush=True)
    while True:
        try:
            text = input('日本語指示 > ')
        except (EOFError, KeyboardInterrupt):
            print(); return 0
        if text.strip().lower() in ('exit', 'quit'):
            return 0
        try:
            validate_input(text, 'GUI')
        except ValueError as e:
            print('入力エラー:', e, flush=True); continue
        # Explicitly invokes the same simulation_cli gateway used by manage.py.
        # All Qwen, C03 and MoveIt gates are performed by the unchanged core.
        cmd = [sys.executable, '-B', str(ROOT / 'tools/simulation_cli.py'),
               'run', '--id', 'GUI', '--authorize-simulation-and-stop-test']
        payload = json.dumps({'id': 'GUI', 'text': text}, ensure_ascii=False)
        print('実行中。RVizと結果ログを確認してください。', flush=True)
        try:
            result = subprocess.run(cmd, input=payload, text=True,
                                    encoding='utf-8', check=False)
            print('終了コード:', result.returncode, flush=True)
            if result.returncode != 0:
                print('失敗または安全停止です。次の指示を出す前にログを確認してください。', flush=True)
                return result.returncode
        except Exception as e:
            print('実行例外:', e, flush=True); return 3

if __name__ == '__main__':
    raise SystemExit(main())
