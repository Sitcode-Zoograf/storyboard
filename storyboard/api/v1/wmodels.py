# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from datetime import datetime

from wsme import types as wtypes

from storyboard.api.v1 import base
from storyboard.common.custom_types import NameType
from storyboard.common import event_resolvers
from storyboard.common import event_types
from storyboard.db.api import comments as comments_api


class Comment(base.APIBase):
    """Any user may leave comments for stories. Also comments api is used by
    gerrit to leave service comments.
    """

    content = wtypes.text
    """The content of the comment."""

    is_active = bool
    """Is this an active comment, or has it been deleted?"""


class SystemInfo(base.APIBase):
    """Represents the system information for Storyboard
    """

    version = wtypes.text
    """The application version."""

    @classmethod
    def sample(cls):
        return cls(
            version="338c2d6")


class Project(base.APIBase):
    """The Storyboard Registry describes the open source world as ProjectGroups
    and Projects. Each ProjectGroup may be responsible for several Projects.
    For example, the OpenStack Infrastructure ProjectGroup has Zuul, Nodepool,
    Storyboard as Projects, among others.
    """

    name = NameType()
    """The Project unique name. This name will be displayed in the URL.
    At least 3 alphanumeric symbols. Minus and dot symbols are allowed as
    separators.
    """

    description = wtypes.text
    """Details about the project's work, highlights, goals, and how to
    contribute. Use plain text, paragraphs are preserved and URLs are
    linked in pages.
    """

    is_active = bool
    """Is this an active project, or has it been deleted?"""

    @classmethod
    def sample(cls):
        return cls(
            name="StoryBoard",
            description="This is an awesome project.",
            is_active=True)


class ProjectGroup(base.APIBase):
    """Represents a group of projects."""

    name = NameType()
    """The Project Group unique name. This name will be displayed in the URL.
    At least 3 alphanumeric symbols. Minus and dot symbols are allowed as
    separators.
    """

    title = wtypes.text
    """The full name of the project group, which can contain spaces, special
    characters, etc.
    """

    @classmethod
    def sample(cls):
        return cls(
            name="Infra",
            title="Awesome projects")


class Story(base.APIBase):
    """The Story is the main element of StoryBoard. It represents a user story
    (generally a bugfix or a feature) that needs to be implemented. It will be
    broken down into a series of Tasks, which will each target a specific
    Project and branch.
    """

    title = wtypes.text
    """A descriptive label for the story, to show in listings."""

    description = wtypes.text
    """A complete description of the goal this story wants to cover."""

    is_bug = bool
    """Is this a bug or a feature :)"""

    creator_id = int
    """User ID of the Story creator"""

    todo = int
    """The number of tasks remaining to be worked on."""

    inprogress = int
    """The number of in-progress tasks for this story."""

    review = int
    """The number of tasks in review for this story."""

    merged = int
    """The number of merged tasks for this story."""

    invalid = int
    """The number of invalid tasks for this story."""

    status = unicode
    """The derived status of the story, one of 'active', 'merged', 'invalid'"""

    @classmethod
    def sample(cls):
        return cls(
            title="Use Storyboard to manage Storyboard",
            description="We should use Storyboard to manage Storyboard.",
            is_bug=False,
            creator_id=1,
            todo=0,
            inprogress=1,
            review=1,
            merged=0,
            invalid=0,
            status="active")


class Task(base.APIBase):
    """A Task represents an actionable work item, targeting a specific Project
    and a specific branch. It is part of a Story. There may be multiple tasks
    in a story, pointing to different projects or different branches. Each task
    is generally linked to a code change proposed in Gerrit.
    """

    title = wtypes.text
    """An optional short label for the task, to show in listings."""

    # TODO(ruhe): replace with enum
    status = wtypes.text
    """Status.
    Allowed values: ['todo', 'inprogress', 'invalid', 'review', 'merged'].
    Human readable versions are left to the UI.
    """

    is_active = bool
    """Is this an active task, or has it been deleted?"""

    creator_id = int
    """Id of the User who has created this Task"""

    story_id = int
    """The ID of the corresponding Story."""

    project_id = int
    """The ID of the corresponding Project."""

    assignee_id = int
    """The ID of the invidiual to whom this task is assigned."""

    priority = wtypes.text
    """The priority for this task, one of 'low', 'medium', 'high'"""


class Team(base.APIBase):
    """The Team is a group od Users with a fixed set of permissions.
    """

    name = NameType()
    """The Team unique name. This name will be displayed in the URL.
    At least 3 alphanumeric symbols. Minus and dot symbols are allowed as
    separators.
    """

    description = wtypes.text
    """Details about the team.
    """

    @classmethod
    def sample(cls):
        return cls(
            name="StoryBoard-core",
            description="Core reviewers of StoryBoard team.")


class TimeLineEvent(base.APIBase):
    """An event object should be created each time a story or a task state
    changes.
    """

    event_type = wtypes.text
    """This type should serve as a hint for the web-client when rendering
    a comment."""

    event_info = wtypes.text
    """A JSON encoded field with details about the event."""

    story_id = int
    """The ID of the corresponding Story."""

    author_id = int
    """The ID of User who has left the comment."""

    comment_id = int
    """The id of a comment linked to this event."""

    comment = Comment
    """The resolved comment."""

    @staticmethod
    def resolve_event_values(event):
        if event.comment_id:
            comment = comments_api.comment_get(event.comment_id)
            event.comment = Comment.from_db_model(comment)

        event = TimeLineEvent._resolve_info(event)

        return event

    @staticmethod
    def _resolve_info(event):
        if event.event_type == event_types.STORY_CREATED:
            return event_resolvers.story_created(event)

        elif event.event_type == event_types.STORY_DETAILS_CHANGED:
            return event_resolvers.story_details_changed(event)

        elif event.event_type == event_types.USER_COMMENT:
            return event_resolvers.user_comment(event)

        elif event.event_type == event_types.TASK_CREATED:
            return event_resolvers.task_created(event)

        elif event.event_type == event_types.TASK_STATUS_CHANGED:
            return event_resolvers.task_status_changed(event)

        elif event.event_type == event_types.TASK_PRIORITY_CHANGED:
            return event_resolvers.task_priority_changed(event)

        elif event.event_type == event_types.TASK_ASSIGNEE_CHANGED:
            return event_resolvers.task_assignee_changed(event)

        elif event.event_type == event_types.TASK_DETAILS_CHANGED:
            return event_resolvers.task_details_changed(event)

        elif event.event_type == event_types.TASK_DELETED:
            return event_resolvers.task_deleted(event)


class User(base.APIBase):
    """Represents a user."""

    username = wtypes.text
    """A short unique name, beginning with a lower-case letter or number, and
    containing only letters, numbers, dots, hyphens, or plus signs"""

    full_name = wtypes.text
    """Full (Display) name."""

    openid = wtypes.text
    """The unique identifier, returned by an OpneId provider"""

    email = wtypes.text
    """Email Address."""

    # Todo(nkonovalov): use teams to define superusers
    is_superuser = bool

    last_login = datetime
    """Date of the last login."""

    enable_login = bool
    """Whether this user is permitted to log in."""

    @classmethod
    def sample(cls):
        return cls(
            username="elbarto",
            full_name="Bart Simpson",
            openid="https://login.launchpad.net/+id/Abacaba",
            email="skinnerstinks@springfield.net",
            is_staff=False,
            is_active=True,
            is_superuser=True,
            last_login=datetime(2014, 1, 1, 16, 42))