# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""empty message

Revision ID: 66918e5b789b
Revises: None
Create Date: 2017-08-03 14:26:56.669191

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '66918e5b789b'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('topic',
                    sa.Column('key', sa.Integer(), nullable=False, quote=True),
                    sa.Column('name', sa.String(length=255), nullable=False),
                    sa.Column('subscribed', sa.Boolean(), nullable=True),
                    sa.Column('description', sa.Text(), nullable=False),
                    sa.Column('updated', sa.DateTime),
                    sa.PrimaryKeyConstraint('key')
                    )
    op.create_index(op.f('ix_topic_name'), 'topic', ['name'], unique=True)
    op.create_index(op.f('ix_topic_subscribed'), 'topic',
                    ['subscribed'], unique=False)
    op.create_table('message',
                    sa.Column('key', sa.Integer(), nullable=False),
                    sa.Column('topic_key', sa.Integer(),
                              sa.ForeignKey('topic.key'), index=True),
                    sa.Column('message', sa.Text(), nullable=False),
                    sa.Column('updated', sa.DateTime),
                    sa.PrimaryKeyConstraint('key')
                    )
    op.create_table('topic_message', sa.Column(
        'key', sa.Integer(),
        nullable=False),
        sa.Column(
        'topic_key', sa.Integer(),
        sa.ForeignKey('topic.key'),
        index=True),
        sa.Column(
        'message_key', sa.Integer(),
        sa.ForeignKey('message.key'),
        index=True),
        sa.Column('sequence', sa.Integer(),
                  nullable=False),
        sa.PrimaryKeyConstraint('key'),
        sa.UniqueConstraint(
        'message_key', 'sequence',
        name='message_key_sequence_const'),)


def downgrade():
    op.drop_index(op.f('ix_topic_subscribed'), table_name='topic')
    op.drop_index(op.f('ix_topic_name'), table_name='topic')
    op.drop_table('topic')
    op.drop_table('message')
    op.drop_table('topic_message')
