#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# delta_sync.py
"""
Инкрементальная синхронизация Битрикс24 → AD.
- Создаёт новых пользователей (с уникальным паролем + отправка в Битрикс24).
- Обновляет ФИО / должность / отдел.
- Перемещает при смене отдела.
- Отключает уволенных (ACTIVE=False) и перемещает в OU=Disabled.
- Удаляет отключённых старше 180 дней.
- Обновляет членство в департаментских группах.
НЕ трогает OU=Protected.

ЗАЩИТА ОТ ЛОЖНЫХ ОТКЛЮЧЕНИЙ:
Перед тем как отключить пользователя, делаем точечный API-запрос
check_bitrix_user_status(uid). Если пользователь в Битрикс24
активен или API вернул ошибку — пропускаем отключение.
"""

import sys
import re
from datetime import datetime, timedelta
from ldap3 import SUBTREE, MODIFY_ADD, MODIFY_REPLACE, MODIFY_DELETE
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

from ad_common import *   # noqa

# ================= Получение AD-пользователей =================
def fetch_ad_users(conn, base_dn):
    """
    Возвращает dict: user_dn -> {
        'uid': str|None,
        'disabled': bool,
        'disabled_at': datetime|None,
        'description': str,
        'cn': str,
        'sam': str,
        'upn': str,
        'mail': str,
        'given': str, 'sn': str,
        'title': str, 'dept_attr': str,
        'dept_ou': str,
    }
    """
    result = {}
    conn.search(base_dn, "(&(objectClass=user)(!(objectClass=computer)))",
                search_scope=SUBTREE,
                attributes=['cn','sAMAccountName','userPrincipalName','mail',
                            'givenName','sn','title','department',
                            'description','userAccountControl'])
    for e in conn.entries:
        try:
            uac = int(e.userAccountControl.value) if e.userAccountControl else 0
            disabled = bool(uac & 2)
            desc = str(e.description) if e.description else ''
            dn = str(e.entry_dn)
            parent = dn.split(',', 1)[1] if ',' in dn else ''
            result[dn] = {
                'uid': parse_uid(desc),
                'disabled': disabled,
                'disabled_at': parse_disabled_at(desc),
                'description': desc,
                'cn': str(e.cn) if e.cn else '',
                'sam': str(e.sAMAccountName) if e.sAMAccountName else '',
                'upn': str(e.userPrincipalName) if e.userPrincipalName else '',
                'mail': str(e.mail) if e.mail else '',
                'given': str(e.givenName) if e.givenName else '',
                'sn': str(e.sn) if e.sn else '',
                'title': str(e.title) if e.title else '',
                'dept_attr': str(e.department) if e.department else '',
                'dept_ou': parent,
            }
        except Exception:
            pass
    return result

# ================= MAIN =================
def main():
    print(f"\n=== DELTA SYNC {datetime.now().isoformat()} ===\n")
    print(f"[CFG] Тестовый режим отправки: "
          f"{'UID=' + TEST_RECIPIENT_ID if TEST_RECIPIENT_ID else 'выключен (всем)'}")
    print(f"[CFG] Длина пароля: {PASSWORD_LENGTH}")

    conn = connect_ad()

    for name, parent in [
        (ROOT_OU_NAME, AD_BASE_DN),
        (DISABLED_OU_NAME, ROOT_OU_DN),
        (PROTECTED_OU_NAME, ROOT_OU_DN),
        (DEPT_GROUPS_OU_NAME, ROOT_OU_DN),
        (GROUPS_OU_NAME, ROOT_OU_DN),
    ]:
        ensure_ou(conn, name, parent, quiet=True)

    # ===== 1. Данные из Битрикса =====
    print("[Bitrix24] Загрузка...")
    departments = get_all_departments()
    groups = get_all_groups()
    active_users = get_active_users()
    inactive_users = get_inactive_users()
    print(f"[Bitrix24] {len(departments)} подразд., {len(groups)} групп, "
          f"активных {len(active_users)}, уволенных {len(inactive_users)}")

    # Sanity-check: пересечение активных и неактивных (сигнал о проблемах API)
    active_ids_set = {u['ID'] for u in active_users}
    inactive_ids_set = {u['ID'] for u in inactive_users}
    overlap = active_ids_set & inactive_ids_set
    if overlap:
        print(f"[WARN] {len(overlap)} UID попали одновременно в active и inactive! "
              f"Примеры: {list(overlap)[:5]}")

    dept_info = {}
    for d in departments:
        did = int(d['ID'])
        head = None
        if d.get('UF_HEAD'):
            try: head = int(d['UF_HEAD'])
            except: pass
        dept_info[did] = {
            'name': d['NAME'], 'parent': int(d.get('PARENT', 0)),
            'head_uid': head,
        }

    # Карты Битрикса (ID — строки, как их отдаёт API)
    bitrix_by_uid = {u['ID']: u for u in active_users + inactive_users}
    bitrix_active_uids = {u['ID'] for u in active_users}
    bitrix_inactive_uids = {u['ID'] for u in inactive_users}

    # ===== 2. Данные из AD =====
    print("[AD] Загрузка пользователей...")
    ad_users = fetch_ad_users(conn, ROOT_OU_DN)
    print(f"[AD] Найдено пользователей: {len(ad_users)}")

    ad_by_uid = {}
    ad_active = []
    ad_disabled = []
    for dn, info in ad_users.items():
        if info['uid'] is not None:
            ad_by_uid[info['uid']] = dn
        if info['disabled']:
            ad_disabled.append(dn)
        else:
            ad_active.append(dn)

    # ===== 3. Сбор кандидатов на отключение =====
    print("\n--- Отключение уволенных ---")
    now = datetime.now()
    candidates = []  # list of (dn, uid, reason)

    # 3.1. В Битриксе ACTIVE=False, в AD активны
    for uid in bitrix_inactive_uids:
        dn = ad_by_uid.get(uid)
        if dn and not ad_users[dn]['disabled']:
            candidates.append((dn, uid, "ACTIVE=False в Битриксе"))

    # 3.2. В AD активны, но UID не в bulk-выборке (потенциально удалён)
    for dn in ad_active:
        uid = ad_users[dn]['uid']
        if uid is None:
            continue
        if uid not in bitrix_by_uid:
            candidates.append((dn, uid, "нет в bulk-выборке Битрикса"))

    print(f"[AD] Кандидатов на отключение: {len(candidates)}")

    # ===== 3.5. Двойная проверка через API (защита от ложных срабатываний) =====
    actual_disable = []
    if candidates:
        print("[AD] Точечная проверка каждого кандидата через API Битрикса...")
        for dn, uid, reason in candidates:
            status = check_bitrix_user_status(uid)
            cn = ad_users[dn]['cn']
            if status == 'active':
                print(f"  [SKIP] {cn} (UID={uid}) — АКТИВЕН в Битриксе, "
                      f"ложное срабатывание ({reason})")
                continue
            if status == 'error':
                print(f"  [SKIP] {cn} (UID={uid}) — ошибка API, "
                      f"не отключаем на всякий случай ({reason})")
                continue
            # status in ('inactive', 'not_found') — можно отключать
            print(f"  [OK]   {cn} (UID={uid}) — статус={status}, "
                  f"причина: {reason}")
            actual_disable.append((dn, uid, reason))

    # ===== 3.6. Фактическое отключение =====
    disabled_cnt = 0
    for dn, uid, reason in actual_disable:
        # Убираем из всех групп
        conn.search(dn, "(objectClass=user)", search_scope='BASE', attributes=['memberOf'])
        if conn.entries and conn.entries[0].memberOf:
            for g in conn.entries[0].memberOf:
                try:
                    conn.modify(str(g), {'member': [(MODIFY_DELETE, [dn])]})
                except Exception:
                    pass

        # Отключаем UAC
        if not disable_user(conn, dn):
            print(f"  [WARN] не удалось отключить {dn}")
            continue

        # Пишем DISABLED_AT в description (атомарно с disable)
        set_disabled_at(conn, dn, uid, now)

        # Перемещаем в OU=Disabled
        if DISABLED_OU_DN not in dn:
            if not move_user(conn, dn, DISABLED_OU_DN):
                print(f"  [WARN] не удалось переместить {dn} в Disabled")

        disabled_cnt += 1
        print(f"  [DISABLED] {ad_users[dn]['cn']} (UID={uid})")
    print(f"[AD] Отключено: {disabled_cnt}")

    # ===== 4. Восстановление: снова ACTIVE=True в Битриксе =====
    print("\n--- Восстановление вернувшихся ---")
    restored = 0
    for uid in bitrix_active_uids:
        dn = ad_by_uid.get(uid)
        if not dn:
            continue
        if not ad_users[dn]['disabled']:
            continue

        if not enable_user(conn, dn):
            print(f"  [WARN] не удалось включить {dn}")
            continue

        # Стираем DISABLED_AT из description
        clear_disabled_at(conn, dn, uid)

        # Вернём в правильный OU
        u = bitrix_by_uid[uid]
        uf = u.get('UF_DEPARTMENT', [])
        if uf:
            try:
                did = int(uf[0])
            except Exception:
                did = None
            if did:
                dept_name = dept_info.get(did, {}).get('name', '')
                target_ou = None
                conn.search(ROOT_OU_DN,
                            f"(&(objectClass=organizationalUnit)(ou={escape_filter_chars(dept_name)}))",
                            search_scope=SUBTREE, attributes=['distinguishedName'])
                if conn.entries:
                    target_ou = str(conn.entries[0].entry_dn)
                if target_ou:
                    move_user(conn, dn, target_ou)
        restored += 1
        print(f"  [RESTORED] {ad_users[dn]['cn']} (UID={uid})")
    print(f"[AD] Восстановлено: {restored}")

    # Перечитываем AD после всех изменений
    ad_users = fetch_ad_users(conn, ROOT_OU_DN)
    ad_by_uid = {i['uid']: dn for dn, i in ad_users.items() if i['uid']}
    ad_active = [dn for dn, i in ad_users.items() if not i['disabled']]

    # ===== 5. Новые пользователи =====
    print("\n--- Новые пользователи ---")
    used_logins = set(i['sam'] for i in ad_users.values() if i['sam'])
    created = 0

    for u in active_users:
        uid = u['ID']
        if uid in ad_by_uid:
            continue
        uf = u.get('UF_DEPARTMENT', [])
        if not uf: continue
        first = (u.get('NAME') or '').strip()
        last = (u.get('LAST_NAME') or '').strip()
        if not first and not last: continue
        try: did = int(uf[0])
        except: continue
        dept_name = dept_info.get(did, {}).get('name', '')
        conn.search(ROOT_OU_DN,
                    f"(&(objectClass=organizationalUnit)(ou={escape_filter_chars(dept_name)}))",
                    search_scope=SUBTREE, attributes=['distinguishedName'])
        if not conn.entries:
            continue
        ou_dn = str(conn.entries[0].entry_dn)

        login = generate_login(first, last, used_logins)
        display = f"{first} {last}".strip()
        user_dn, actual = make_unique_dn(conn, display, ou_dn)
        email = (u.get('EMAIL') or '').strip()
        attrs = {
            'cn': actual, 'sAMAccountName': login,
            'userPrincipalName': f"{login}@{AD_UPN_SUFFIX}",
            'givenName': first, 'sn': last, 'displayName': actual,
            'company': COMPANY_NAME,
            'description': build_description(uid),
        }
        if dept_name: attrs['department'] = dept_name[:64]
        if u.get('WORK_POSITION'): attrs['title'] = u['WORK_POSITION'][:64]
        if valid_email(email): attrs['mail'] = email
        try:
            conn.add(user_dn, ['user'], attrs)
            if conn.result['description'] == 'success':
                user_password = generate_password()
                pwd_ok = True

                try:
                    conn.extend.microsoft.modify_password(user_dn, user_password)
                    conn.modify(user_dn, {'userAccountControl': [(MODIFY_REPLACE, [512])]})
                except Exception as e:
                    pwd_ok = False
                    print(f"  [WARN] пароль {display}: {e}")
                print(f"  [NEW] {display} ({login})")
                created += 1

                if pwd_ok:
                    store_encrypted_password(user_dn, user_password)
                send_b24_credentials_message(uid, login, user_password, email, user_dn=user_dn, ad_password_set=pwd_ok)
        except Exception as e:
            print(f"  [ERROR] {display}: {e}")
    print(f"[AD] Создано: {created}")

    # ===== 6. Обновление изменений =====
    print("\n--- Обновление изменений ---")
    ad_users = fetch_ad_users(conn, ROOT_OU_DN)
    ad_by_uid = {i['uid']: dn for dn, i in ad_users.items() if i['uid']}

    updated = 0
    moved = 0
    for u in active_users:
        uid = u['ID']
        dn = ad_by_uid.get(uid)
        if not dn:
            continue
        info = ad_users[dn]
        if info['disabled']:
            continue

        first = (u.get('NAME') or '').strip()
        last = (u.get('LAST_NAME') or '').strip()
        if not first and not last: continue
        if not last: last = first
        if not first: first = last
        display = f"{first} {last}".strip()

        changes = {}
        if info['given'] != first: changes['givenName'] = [(MODIFY_REPLACE, [first])]
        if info['sn'] != last: changes['sn'] = [(MODIFY_REPLACE, [last])]
        pos = (u.get('WORK_POSITION') or '').strip()
        if info['title'] != pos[:64]: changes['title'] = [(MODIFY_REPLACE, [pos[:64]])]
        mail = (u.get('EMAIL') or '').strip()
        if info['mail'] != mail and valid_email(mail):
            changes['mail'] = [(MODIFY_REPLACE, [mail])]

        uf = u.get('UF_DEPARTMENT', [])
        if uf:
            try: did = int(uf[0])
            except: did = None
            if did:
                dept_name = dept_info.get(did, {}).get('name', '')
                if dept_name:
                    conn.search(ROOT_OU_DN,
                                f"(&(objectClass=organizationalUnit)(ou={escape_filter_chars(dept_name)}))",
                                search_scope=SUBTREE, attributes=['distinguishedName'])
                    if conn.entries:
                        target_ou = str(conn.entries[0].entry_dn)
                        cur_parent = dn.split(',', 1)[1] if ',' in dn else ''
                        if target_ou != cur_parent and DISABLED_OU_DN not in dn:
                            if move_user(conn, dn, target_ou):
                                moved += 1
                                print(f"  [MOVED] {display} → {dept_name}")
                                changes['department'] = [(MODIFY_REPLACE, [dept_name[:64]])]

        if changes:
            try:
                conn.modify(dn, changes)
                if conn.result['description'] == 'success':
                    updated += 1
                    print(f"  [UPDATED] {display}")
            except Exception as e:
                print(f"  [WARN] {display}: {e}")
    print(f"[AD] Обновлено: {updated}, перемещено: {moved}")

    # ===== 7. Руководители =====
    print("\n--- Обновление руководителей ---")
    uid_to_dn = {}
    uid_to_dept = {}
    for u in active_users:
        dn = ad_by_uid.get(u['ID'])
        if not dn: continue
        uid_to_dn[u['ID']] = dn
        uf = u.get('UF_DEPARTMENT', [])
        if uf:
            try: uid_to_dept[u['ID']] = int(uf[0])
            except: pass

    mgr_set = 0
    for u in active_users:
        uid = u['ID']
        dn = uid_to_dn.get(uid)
        if not dn: continue
        head = None
        if u.get('UF_HEAD'):
            try: head = int(u['UF_HEAD'])
            except: pass
        if head is None:
            did = uid_to_dept.get(uid)
            if did:
                head = dept_info.get(did, {}).get('head_uid')
        if not head or head == uid or head not in uid_to_dn:
            continue
        try:
            conn.modify(dn, {'manager': [(MODIFY_REPLACE, [uid_to_dn[head]])]})
            if conn.result['description'] == 'success':
                mgr_set += 1
        except Exception:
            pass
    print(f"[AD] Обновлено руководителей: {mgr_set}")

    # ===== 8. Членство в департаментских группах =====
    print("\n--- Обновление департаментского членства ---")
    ancestors = build_dept_ancestors(dept_info)
    dept_groups = {}
    conn.search(DEPT_GROUPS_OU_DN, "(objectClass=group)", search_scope=SUBTREE,
                attributes=['distinguishedName','description'])
    for e in conn.entries:
        desc = str(e.description) if e.description else ''
        m = re.search(r'B24_DEPT_ID=(\d+)', desc)
        if m:
            dept_groups[int(m.group(1))] = str(e.entry_dn)

    desired = {}
    for uid, dn in uid_to_dn.items():
        did = uid_to_dept.get(uid)
        if not did:
            continue
        for anc in ancestors.get(did, []):
            gdn = dept_groups.get(anc)
            if gdn:
                desired.setdefault(gdn, set()).add(dn.lower())

    added_cnt = 0
    removed_cnt = 0
    for gdn, want in desired.items():
        conn.search(gdn, "(objectClass=group)", search_scope='BASE', attributes=['member'])
        current = set()
        if conn.entries and conn.entries[0].member:
            current = {str(m).lower() for m in conn.entries[0].member}
        active_dns = {dn.lower() for dn in uid_to_dn.values()}
        want = want & active_dns

        to_add = want - current
        for u in to_add:
            for orig_dn in uid_to_dn.values():
                if orig_dn.lower() == u:
                    try:
                        conn.modify(gdn, {'member': [(MODIFY_ADD, [orig_dn])]})
                        if conn.result['description'] == 'success':
                            added_cnt += 1
                    except Exception:
                        pass
                    break
        to_remove = current - want
        for u in to_remove:
            if u not in active_dns:
                continue
            for orig_dn in uid_to_dn.values():
                if orig_dn.lower() == u:
                    try:
                        conn.modify(gdn, {'member': [(MODIFY_DELETE, [orig_dn])]})
                        if conn.result['description'] == 'success':
                            removed_cnt += 1
                    except Exception:
                        pass
                    break
    print(f"[AD] Департаментское членство: +{added_cnt}, -{removed_cnt}")

    # ===== 9. Удаление старых отключённых =====
    print("\n--- Очистка старых отключённых (>6 мес) ---")
    threshold = now - timedelta(days=DISABLED_RETENTION_DAYS)
    deleted_cnt = 0
    skipped_no_date = 0
    conn.search(DISABLED_OU_DN, "(&(objectClass=user)(!(objectClass=computer)))",
                search_scope=SUBTREE, attributes=['distinguishedName','description'])
    for e in conn.entries:
        dn = str(e.entry_dn)
        desc = str(e.description) if e.description else ''
        dt = parse_disabled_at(desc)
        if not dt:
            # Нет DISABLED_AT — не можем судить о возрасте, пропускаем
            skipped_no_date += 1
            continue
        if dt < threshold:
            try:
                conn.delete(dn)
                if conn.result['description'] == 'success':
                    deleted_cnt += 1
                    print(f"  [DELETED] {dn}")
            except Exception as ex:
                print(f"  [WARN] {dn}: {ex}")
    print(f"[AD] Удалено: {deleted_cnt} (без DISABLED_AT пропущено: {skipped_no_date})")

    # ===== 10. Сводка =====
    ad_users = fetch_ad_users(conn, ROOT_OU_DN)
    active = sum(1 for i in ad_users.values() if not i['disabled'])
    disabled = sum(1 for i in ad_users.values() if i['disabled'])
    print("\n" + "=" * 55)
    print(f"  Битрикс: активных {len(active_users)}, уволенных {len(inactive_users)}")
    print(f"  AD: активных {active}, отключённых {disabled}")
    print(f"  Действия: создано {created}, отключено {disabled_cnt}, "
          f"восстановлено {restored}, обновлено {updated}, "
          f"перемещено {moved}, удалено {deleted_cnt}")
    print("=" * 55 + "\n")

    conn.unbind()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)