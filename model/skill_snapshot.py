from __init__ import app, db
from datetime import datetime, timezone

class SkillSnapshot(db.Model):
    __tablename__ = 'skill_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_name = db.Column(db.String(64), nullable=False)
    snapshot_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    coding_ability = db.Column(db.Integer, nullable=False)
    collaboration = db.Column(db.Integer, nullable=False)
    problem_solving = db.Column(db.Integer, nullable=False)
    initiative = db.Column(db.Integer, nullable=False)

    user = db.relationship('User', backref=db.backref('skill_snapshots', cascade='all, delete-orphan'))

    def __init__(self, user_id, project_name, coding_ability, collaboration, problem_solving, initiative):
        self.user_id = user_id
        self.project_name = project_name
        self.coding_ability = coding_ability
        self.collaboration = collaboration
        self.problem_solving = problem_solving
        self.initiative = initiative

    def read(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'project_name': self.project_name,
            'snapshot_date': self.snapshot_date.isoformat() if self.snapshot_date else None,
            'coding_ability': self.coding_ability,
            'collaboration': self.collaboration,
            'problem_solving': self.problem_solving,
            'initiative': self.initiative
        }

    def create(self):
        db.session.add(self)
        db.session.commit()
        return self