-- Hollowmere Family Health patient portal — seed data (spec 045).
--
-- Every name, record number, address and note here is invented. There is no
-- real clinic, no real patient, and nothing resembling a real record format.
--
-- Two flags are written into this database at container start rather than being
-- baked here: the IDOR flag into record 1043's notes, and the SQLi flag into
-- portal_setting. See flags.py and db.py.

CREATE TABLE portal_user (
    id       INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    role     TEXT NOT NULL,
    fullname TEXT NOT NULL
);

-- Row 1 is the administrator, deliberately: the injected login lands on the
-- first row the query returns, and the admin dashboard is what it is for.
INSERT INTO portal_user (id, username, password, role, fullname) VALUES
    (1, 'h.mercer',    'Winter2011!',  'admin', 'Harriet Mercer'),
    (2, 'd.okonkwo',   'portal2011',   'staff', 'Daniel Okonkwo'),
    (3, 'p.abernathy', 'springfield',  'patient', 'Priya Abernathy'),
    (4, 'j.lindqvist', 'hollowmere',   'patient', 'Jonas Lindqvist');

CREATE TABLE record (
    id        INTEGER PRIMARY KEY,
    owner_id  INTEGER NOT NULL,
    patient   TEXT NOT NULL,
    born      TEXT NOT NULL,
    physician TEXT NOT NULL,
    seen_on   TEXT NOT NULL,
    summary   TEXT NOT NULL,
    notes     TEXT NOT NULL
);

-- 1035-1050, so incrementing or decrementing from the player's own 1042 lands
-- on a plausible neighbour rather than a 404 wall.
INSERT INTO record (id, owner_id, patient, born, physician, seen_on, summary, notes) VALUES
    (1035, 4, 'Jonas Lindqvist',   '1968-04-02', 'Dr E. Vance',   '2011-01-14',
     'Annual review. Unremarkable.',
     'Patient reports sleeping better since changing shifts.'),
    (1036, 4, 'Marguerite Oyelaran','1954-11-30','Dr E. Vance',   '2011-01-19',
     'Follow-up, left knee.',
     'Physiotherapy referral sent. Patient walking without the stick.'),
    (1037, 4, 'Callum Restrick',   '1989-07-21', 'Dr S. Aluko',   '2011-02-03',
     'Persistent cough, four weeks.',
     'Chest clear. Advised to return if no better by the end of the month.'),
    (1038, 4, 'Ingrid Thorsen',    '1977-02-08', 'Dr S. Aluko',   '2011-02-11',
     'Medication review.',
     'Dosage unchanged. Patient asked about the generic; explained it is the same.'),
    (1039, 4, 'Beatriz Sandoval',  '1993-09-17', 'Dr E. Vance',   '2011-02-22',
     'New patient registration.',
     'Transferred from another practice. Records requested, not yet arrived.'),
    (1040, 4, 'Osgood Pell',       '1946-06-05', 'Dr N. Harrow',  '2011-03-01',
     'Blood pressure check.',
     'Slightly raised. Booked for a second reading in a fortnight.'),
    (1041, 4, 'Delphine Aubry',    '1982-12-12', 'Dr N. Harrow',  '2011-03-08',
     'Dressing change.',
     'Healing well. No sign of infection. Next change Thursday.'),
    (1042, 3, 'Priya Abernathy',   '1985-03-26', 'Dr E. Vance',   '2011-03-15',
     'Routine appointment.',
     'Nothing of concern. Patient asked for a copy of her own record; provided.'),
    (1043, 4, 'Theodore Wainfleet','1961-08-19', 'Dr N. Harrow',  '2011-03-16',
     'Results discussion.',
     'PLACEHOLDER — overwritten at container start.'),
    (1044, 4, 'Astrid Bellhaven',  '1998-05-04', 'Dr S. Aluko',   '2011-03-21',
     'Travel vaccinations.',
     'Course started. Second dose due before departure in May.'),
    (1045, 4, 'Cornelius Fitch',   '1939-10-28', 'Dr N. Harrow',  '2011-03-29',
     'Home visit.',
     'Daughter present. Stair rail installed. Patient in good spirits.'),
    (1046, 4, 'Yusra Al-Habib',    '1990-01-09', 'Dr E. Vance',   '2011-04-04',
     'Sprained wrist.',
     'Strapped. Advised against lifting for a fortnight. Patient unconvinced.'),
    (1047, 4, 'Rowan Tasker',      '1973-07-14', 'Dr S. Aluko',   '2011-04-12',
     'Dermatology referral.',
     'Referral letter sent. Patient warned the wait is long.'),
    (1048, 4, 'Henrietta Coombes', '1958-11-02', 'Dr E. Vance',   '2011-04-18',
     'Hearing test.',
     'Mild loss, left ear. Audiology appointment offered and accepted.'),
    (1049, 4, 'Emeka Nwachukwu',   '1986-02-27', 'Dr N. Harrow',  '2011-04-25',
     'Post-operative check.',
     'Sutures out. Wound clean. Signed off.'),
    (1050, 4, 'Vesna Petrovic',    '1969-09-30', 'Dr S. Aluko',   '2011-05-02',
     'Repeat prescription query.',
     'Pharmacy had the wrong address on file. Corrected.');

CREATE TABLE portal_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO portal_setting (key, value) VALUES
    ('site_name',    'Hollowmere Family Health'),
    ('portal_build', '2011.4.2-rc1'),
    ('admin_notice', 'PLACEHOLDER — overwritten at container start.');
