#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# full_sync.py
"""
Полная синхронизация Битрикс24 → AD.
Создаёт OU, группы (Bitrix sonet + департаментские), пользователей,
назначает руководителей, выдаёт админские права.
Идемпотентен. НЕ трогает OU=Disabled и OU=Protected.
При создании нового пользователя генерирует уникальный пароль
и отправляет учётные данные в личные сообщения Битрикс24.
"""

import sys
from datetime import datetime
from ldap3 import SUBTREE, MODIFY_ADD, MODIFY_REPLACE
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn
from ldap3.core.exceptions import LDAPEntryAlreadyExistsResult

from ad_common import *   # noqa

# ================= DE =================
def create_department_tree(conn, departments, active_ids):
    dept_map = {int(d['ID']): {
        'name': d['NAME'],
        'parent': int(d.get('PARENT', 0)),
        'ou_dn': None,
    } for d in departments}

    def expand(ids):
        result = set(ids)
        q = list(ids)
        while q:
            i = q.pop()
            p = dept_map.get(i, {}).get('parent', 0)
            if p and p in dept_map and p not in result:
                result.add(p)
                q.append(p)
        return result

    active_ids = expand(active_ids)
    print(f"[AD] Активных отделов: {len(active_ids)} из {len(dept_map)}")

    def build(did):
        if did not in active_ids:
            return None
        if dept_map[did]['ou_dn']:
            return dept_map[did]['ou_dn']
        parent = dept_map[did]['parent']
        parent_dn = ROOT_OU_DN if (parent == 0 or parent not in dept_map) else (build(parent) or ROOT_OU_DN)
        dept_map[did]['ou_dn'] = ensure_ou(conn, dept_map[did]['name'], parent_dn)
        return dept_map[did]['ou_dn']

    for did in dept_map:
        build(did)
    result = {k: v['ou_dn'] for k, v in dept_map.items() if v['ou_dn']}
    print(f"[AD] Создано/проверено OU: {len(result)}")
    return result

# ================= Bitrix sonet groups =================
def sync_bitrix_groups(conn, groups):
    ensure_ou(conn, GROUPS_OU_NAME, ROOT_OU_DN)
    result = {}
    for g in groups:
        gid = int(g['ID'])
        marker = f"B24_GROUP_ID={gid}"
        existing = find_group_by_marker(conn, GROUPS_OU_DN, marker)
        if existing:
            result[gid] = existing
            continue

        safe = "".join(c for c in g['NAME'] if c.isalnum() or c in " -_").strip()[:64]
        if not safe:
            safe = f"B24_Group_{gid}"
        gdn, actual = make_unique_dn(conn, safe, GROUPS_OU_DN)
        sam = f"{actual[:15]}_{gid}"[:20]
        try:
            conn.add(gdn, ['group'], {
                'cn': actual, 'sAMAccountName': sam,
                'groupType': -2147483646,
                'description': marker,
            })
            if conn.result['description'] == 'success':
                print(f"  [NEW] Группа Bitrix: {actual} (ID={gid})")
            result[gid] = gdn
        except LDAPEntryAlreadyExistsResult:
            result[gid] = gdn
        except Exception as e:
            print(f"  [ERROR] группа {actual}: {e}")
    print(f"[AD] Создано/проверено Bitrix-групп: {len(result)}")
    return result

# ================= Департаментские группы =================
def sync_dept_groups(conn, dept_ou_map, dept_info):
    ensure_ou(conn, DEPT_GROUPS_OU_NAME, ROOT_OU_DN)
    result = {}
    for did, ou_dn in dept_ou_map.items():
        dept_name = dept_info.get(did, {}).get('name', f'Dept_{did}')
        marker = f"B24_DEPT_ID={did}"
        existing = find_group_by_marker(conn, DEPT_GROUPS_OU_DN, marker)
        if existing:
            result[did] = existing
            continue
        safe = (DEPT_GROUP_PREFIX + dept_name)[:64]
        gdn, actual = make_unique_dn(conn, safe, DEPT_GROUPS_OU_DN)
        sam = f"{actual[:15]}_{did}"[:20]
        try:
            conn.add(gdn, ['group'], {
                'cn': actual, 'sAMAccountName': sam,
                'groupType': -2147483646,
                'description': marker,
            })
            if conn.result['description'] == 'success':
                print(f"  [NEW] Группа отдела: {actual}")
            result[did] = gdn
        except LDAPEntryAlreadyExistsResult:
            result[did] = gdn
        except Exception as e:
            print(f"  [ERROR] группа отдела {actual}: {e}")
    print(f"[AD] Создано/проверено департаментских групп: {len(result)}")
    return result

def sync_dept_membership(conn, dept_ou_map, dept_info, uid_to_dn, uid_to_dept_id, dept_group_dn):
    ancestors = build_dept_ancestors(dept_info)
    desired = {}
    for uid, user_dn in uid_to_dn.items():
        did = uid_to_dept_id.get(uid)
        if not did:
            continue
        for anc_id in ancestors.get(did, []):
            gdn = dept_group_dn.get(anc_id)
            if gdn:
                desired.setdefault(gdn, set()).add(user_dn.lower())

    added = 0
    for gdn, want_users in desired.items():
        conn.search(gdn, "(objectClass=group)", search_scope='BASE', attributes=['member'])
        current = set()
        if conn.entries and conn.entries[0].member:
            current = {str(m).lower() for m in conn.entries[0].member}
        to_add = want_users - current
        for u in to_add:
            for uid, dn in uid_to_dn.items():
                if dn.lower() == u:
                    try:
                        conn.modify(gdn, {'member': [(MODIFY_ADD, [dn])]})
                        if conn.result['description'] == 'success':
                            added += 1
                    except Exception as e:
                        print(f"  [WARN] членство {dn} в {gdn}: {e}")
                    break
    print(f"[AD] Добавлено в департаментские группы: {added}")

# ================= Пользователи =================
def find_existing_user(conn, uid, login, email):
    marker = f"B24_UID={uid}"
    conn.search(ROOT_OU_DN, f"(&(objectClass=user)(description={marker}))",
                search_scope=SUBTREE, attributes=['distinguishedName'])
    if conn.entries:
        return str(conn.entries[0].entry_dn)
    upn = f"{login}@{AD_UPN_SUFFIX}"
    conn.search(ROOT_OU_DN, f"(userPrincipalName={escape_filter_chars(upn)})",
                search_scope=SUBTREE, attributes=['distinguishedName'])
    if conn.entries:
        return str(conn.entries[0].entry_dn)
    if email and "@" in email:
        conn.search(ROOT_OU_DN, f"(mail={escape_filter_chars(email)})",
                    search_scope=SUBTREE, attributes=['distinguishedName'])
        if conn.entries:
            return str(conn.entries[0].entry_dn)
    return None

def create_or_get_user(conn, u, ou_dn, login, dept_name):
    uid = u['ID']
    first = (u.get('NAME') or '').strip()
    last = (u.get('LAST_NAME') or '').strip()
    email = (u.get('EMAIL') or '').strip()
    pos = (u.get('WORK_POSITION') or '').strip()
    if not first and not last:
        return None, 'failed'
    if not last: last = first
    if not first: first = last

    existing = find_existing_user(conn, uid, login, email)
    if existing:
        return existing, 'existing'

    display = f"{first} {last}".strip()
    user_dn, actual = make_unique_dn(conn, display, ou_dn)
    attrs = {
        'cn': actual, 'sAMAccountName': login,
        'userPrincipalName': f"{login}@{AD_UPN_SUFFIX}",
        'givenName': first, 'sn': last, 'displayName': actual,
        'company': COMPANY_NAME,
        'description': build_description(uid),
    }
    if dept_name: attrs['department'] = dept_name[:64]
    if pos: attrs['title'] = pos[:64]
    if valid_email(email): attrs['mail'] = email

    try:
        conn.add(user_dn, ['user'], attrs)
    except LDAPConstraintViolationResult as e:
        print(f"  [ERROR] UPN конфликт {display}: {e}")
        return None, 'failed'
    except LDAPEntryAlreadyExistsResult:
        return user_dn, 'existing'
    except Exception as e:
        print(f"  [ERROR] {display}: {e}")
        return None, 'failed'

    if conn.result['description'] != 'success':
        return None, 'failed'

    # 🔐 Генерируем уникальный пароль для каждого пользователя
    user_password = generate_password()

    try:
        conn.extend.microsoft.modify_password(user_dn, user_password)
    except Exception as e:
        print(f"  [WARN] пароль {display}: {e}")
        # Даже если пароль не установился — сообщение отправим, чтобы
        # пользователь знал логин и мог запросить сброс.
        send_b24_credentials_message(uid, login, user_password, email, user_dn=user_dn, ad_password_set=False)
        return user_dn, 'created'

    try:
        conn.modify(user_dn, {'userAccountControl': [(MODIFY_REPLACE, [512])]})
    except Exception:
        pass

    print(f"  [NEW] {display} ({login})")

    # 💾 Сохраняем пароль (зашифрованным), чтобы потом можно было "напомнить"
    store_encrypted_password(user_dn, user_password)

    # ✉️ Отправляем учётные данные в Битрикс24
    send_b24_credentials_message(uid, login, user_password, email, user_dn=user_dn)

    return user_dn, 'created'

# ================= Руководители =================
def sync_managers(conn, users, uid_to_dn, uid_to_dept_id, dept_info):
    existing = set()
    conn.search(ROOT_OU_DN, "(&(objectClass=user)(manager=*))",
                search_scope=SUBTREE, attributes=['distinguishedName'])
    for e in conn.entries:
        existing.add(str(e.entry_dn))

    set_cnt, skip_cnt = 0, 0
    for u in users:
        uid = u['ID']
        dn = uid_to_dn.get(uid)
        if not dn or dn in existing:
            continue
        head = None
        if u.get('UF_HEAD'):
            try: head = int(u['UF_HEAD'])
            except: head = None
        if head is None:
            did = uid_to_dept_id.get(uid)
            if did:
                head = dept_info.get(did, {}).get('head_uid')
        if not head or head == uid or head not in uid_to_dn:
            skip_cnt += 1
            continue
        try:
            conn.modify(dn, {'manager': [(MODIFY_REPLACE, [uid_to_dn[head]])]})
            if conn.result['description'] == 'success':
                set_cnt += 1
        except Exception:
            pass
    print(f"[AD] Руководителей назначено: {set_cnt}, пропущено: {skip_cnt}")

# ================= Админские права =================
def grant_admin_rights(conn, uid_to_dn, uid_to_dept_id, dept_info):
    conn.search(AD_BASE_DN,
                f"(&(objectClass=group)(cn={escape_filter_chars(ADMIN_GROUP_NAME)}))",
                search_scope=SUBTREE, attributes=['distinguishedName', 'member'])
    if not conn.entries:
        print(f"  [ERROR] Группа «{ADMIN_GROUP_NAME}» не найдена")
        return 0
    admin_dn = str(conn.entries[0].entry_dn)
    current = set()
    if conn.entries[0].member:
        current = {str(m).lower() for m in conn.entries[0].member}
    added = 0
    for uid, dn in uid_to_dn.items():
        did = uid_to_dept_id.get(uid)
        if not did:
            continue
        name = (dept_info.get(did, {}).get('name') or '').lower()
        if any(kw in name for kw in ADMIN_DEPT_KEYWORDS):
            if dn.lower() in current:
                continue
            try:
                conn.modify(admin_dn, {'member': [(MODIFY_ADD, [dn])]})
                if conn.result['description'] == 'success':
                    added += 1
                    print(f"  [ADMIN] + {dn}")
            except Exception as e:
                print(f"  [WARN] {dn}: {e}")
    return added

# ================= Очистка пустых OU =================
def cleanup_empty_ous(conn, root_dn):
    total = 0
    while True:
        conn.search(root_dn, "(objectClass=organizationalUnit)",
                    search_scope=SUBTREE, attributes=['distinguishedName'])
        ous = sorted(
            [str(e.entry_dn) for e in conn.entries
             if str(e.entry_dn) not in (root_dn, DISABLED_OU_DN, PROTECTED_OU_DN)
             and not str(e.entry_dn).endswith(f"OU={DISABLED_OU_NAME},{root_dn}")
             and not str(e.entry_dn).endswith(f"OU={PROTECTED_OU_NAME},{root_dn}")],
            key=len, reverse=True)
        deleted = 0
        for dn in ous:
            conn.search(dn, "(|(objectClass=user)(objectClass=organizationalUnit)(objectClass=group))",
                        search_scope='LEVEL', attributes=['distinguishedName'])
            if len(conn.entries) == 0:
                conn.delete(dn)
                if conn.result['description'] == 'success':
                    deleted += 1
        total += deleted
        if deleted == 0:
            break
    if total:
        print(f"[AD] Удалено пустых OU: {total}")

# ================= MAIN =================
def main():
    print(f"\n=== FULL SYNC {datetime.now().isoformat()} ===\n")
    print(f"[CFG] Тестовый режим отправки: "
          f"{'UID=' + TEST_RECIPIENT_ID if TEST_RECIPIENT_ID else 'выключен (всем)'}")
    print(f"[CFG] Длина пароля: {PASSWORD_LENGTH}")

    conn = connect_ad()

    ensure_ou(conn, ROOT_OU_NAME, AD_BASE_DN)
    ensure_ou(conn, DISABLED_OU_NAME, ROOT_OU_DN)
    ensure_ou(conn, PROTECTED_OU_NAME, ROOT_OU_DN)

    print("\n--- Загрузка данных из Битрикс24 ---")
    departments = get_all_departments()
    groups = get_all_groups()
    users = get_active_users()
    print(f"[Bitrix24] {len(departments)} подразд., {len(groups)} групп, {len(users)} польз.")

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

    active_ids = set()
    for u in users:
        for d in u.get('UF_DEPARTMENT', []) or []:
            try: active_ids.add(int(d))
            except: pass

    print("\n--- Создание OU-структуры ---")
    dept_ou_map = create_department_tree(conn, departments, active_ids)

    print("\n--- Создание Bitrix-групп ---")
    sync_bitrix_groups(conn, groups)

    print("\n--- Создание департаментских групп ---")
    dept_group_dn = sync_dept_groups(conn, dept_ou_map, dept_info)

    print("\n--- Создание/поиск пользователей ---")
    used_logins = set()
    uid_to_dn, uid_to_dept_id = {}, {}
    created = existing = failed = 0

    for u in users:
        uid = u['ID']
        uf = u.get('UF_DEPARTMENT', [])
        if not uf: continue
        first = (u.get('NAME') or '').strip()
        last = (u.get('LAST_NAME') or '').strip()
        if not first and not last: continue
        try: did = int(uf[0])
        except: continue
        ou_dn = dept_ou_map.get(did)
        if not ou_dn: continue
        dept_name = dept_info.get(did, {}).get('name', '')
        login = generate_login(first, last, used_logins)

        dn, status = create_or_get_user(conn, u, ou_dn, login, dept_name)
        if dn:
            uid_to_dn[uid] = dn
            uid_to_dept_id[uid] = did
            if status == 'created': created += 1
            else: existing += 1
        else:
            failed += 1

    print(f"[AD] Создано: {created}, найдено: {existing}, ошибок: {failed}")

    print("\n--- Назначение руководителей ---")
    sync_managers(conn, users, uid_to_dn, uid_to_dept_id, dept_info)

    print("\n--- Департаментское членство ---")
    sync_dept_membership(conn, dept_ou_map, dept_info, uid_to_dn, uid_to_dept_id, dept_group_dn)

    print("\n--- Админские права ---")
    n = grant_admin_rights(conn, uid_to_dn, uid_to_dept_id, dept_info)
    print(f"[AD] Добавлено в «{ADMIN_GROUP_NAME}»: {n}")

    print("\n--- Очистка пустых OU ---")
    cleanup_empty_ous(conn, ROOT_OU_DN)

    conn.search(ROOT_OU_DN, "(&(objectClass=user)(!(objectClass=computer)))",
                search_scope=SUBTREE, attributes=['distinguishedName'])
    ad_u = len(conn.entries)
    print(f"[AD] Пользователей в AD: {ad_u}")
    print(f"\n=== FULL SYNC ЗАВЕРШЕН ===\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)