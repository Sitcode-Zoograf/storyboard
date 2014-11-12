# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json
import re
import sys

from openid.consumer import consumer
from openid.consumer.discover import DiscoveryFailure
from openid import cryptutil

import storyboard.common.event_types as event_types
from storyboard.db.api import base as db_api
from storyboard.db.api import comments as comments_api
from storyboard.db.api import projects as projects_api
from storyboard.db.api import tags as tags_api
from storyboard.db.api import users as users_api
from storyboard.db.models import Story
from storyboard.db.models import Task
from storyboard.db.models import TimeLineEvent


class LaunchpadWriter(object):
    def __init__(self, project_name):
        """Create a new instance of the launchpad-to-storyboard data writer.
        """

        # username -> openid
        self._openid_map = dict()
        # openid -> SB User Entity
        self._user_map = dict()
        # tag_name -> SB StoryTag Entity
        self._tag_map = dict()

        # SB Project Entity + Sanity check.
        self.project = projects_api.project_get_by_name(project_name)
        if not self.project:
            print "Local project %s not found in storyboard, please create " \
                  "it first." % (project_name)
            sys.exit(1)

    def write_tags(self, bug):
        """Extracts the tags from a launchpad bug, seeds/loads them in the
        StoryBoard database, and returns a list of the corresponding entities.
        """
        tags = list()

        # Make sure the tags field exists and has some content.
        if hasattr(bug, 'tags') and bug.tags:
            for tag_name in bug.tags:
                tags.append(self.build_tag(tag_name))

        return tags

    def build_tag(self, tag_name):
        """Retrieve the SQLAlchemy record for the given tag name, creating it
        if necessary.

        :param tag_name: Name of the tag to retrieve and/or create.
        :return: The SQLAlchemy entity corresponding to the tag name.
        """
        if tag_name not in self._tag_map:

            # Does it exist in the database?
            tag = tags_api.tag_get_by_name(tag_name)

            if not tag:
                # Go ahead and create it.
                print "Importing tag '%s'" % (tag_name)
                tag = tags_api.tag_create(dict(
                    name=tag_name
                ))

            # Add it to our memory cache
            self._tag_map[tag_name] = tag

        return self._tag_map[tag_name]

    def write_user(self, lp_user):
        """Writes a launchpad user record into our user cache, resolving the
        openid if necessary.

        :param lp_user: The launchpad user record.
        :return: The SQLAlchemy entity for the user record.
        """
        if lp_user is None:
            return lp_user

        username = lp_user.name
        display_name = lp_user.display_name
        user_link = lp_user.web_link

        # Resolve the openid.
        if user_link not in self._openid_map:
            try:
                openid_consumer = consumer.Consumer(
                    dict(id=cryptutil.randomString(16, '0123456789abcdef')),
                    None)
                openid_request = openid_consumer.begin(user_link)
                openid = openid_request.endpoint.getLocalID()

                self._openid_map[user_link] = openid
            except DiscoveryFailure:
                # If we encounter a launchpad maintenance user,
                # give it an invalid openid.
                print "WARNING: Invalid OpenID for user \'%s\'" % (username,)
                self._openid_map[user_link] = \
                    'http://example.com/invalid/~%s' % (username,)

        openid = self._openid_map[user_link]

        # Resolve the user record from the openid.
        if openid not in self._user_map:

            # Check for the user, create if new.
            user = users_api.user_get_by_openid(openid)
            if not user:
                print "Importing user '%s'" % (user_link)

                # Use a temporary email address, since LP won't give this to
                # us and it'll be updated on first login anyway.
                user = users_api.user_create({
                    'username': username,
                    'openid': openid,
                    'full_name': display_name,
                    'email': "%s@example.com" % (username)
                })

            self._user_map[openid] = user

        return self._user_map[openid]

    def write_bug(self, owner, assignee, priority, status, tags, bug):
        """Writes the story, task, task history, and conversation.

        :param owner: The bug owner SQLAlchemy entity.
        :param tags: The tag SQLAlchemy entities.
        :param bug: The Launchpad Bug record.
        """

        if hasattr(bug, 'date_created'):
            created_at = bug.date_created.strftime('%Y-%m-%d %H:%M:%S')
        else:
            created_at = None

        if hasattr(bug, 'date_last_updated'):
            updated_at = bug.date_last_updated.strftime('%Y-%m-%d %H:%M:%S')
        else:
            updated_at = None

        # Extract the launchpad ID from the self link.
        # example url: https://api.launchpad.net/1.0/bugs/1057477
        url_match = re.search("([0-9]+)$", str(bug.self_link))
        if not url_match:
            print 'ERROR: Unable to extract launchpad ID from %s.' \
                  % (bug.self_link,)
            print 'ERROR: Please file a ticket.'
            return
        launchpad_id = int(url_match.groups()[0])

        print "Importing %s" % (bug.self_link,)

        # If the title is too long, prepend it to the description and
        # truncate it.
        title = bug.title
        description = bug.description

        if len(title) > 100:
            title = title[:97] + '...'
            description = bug.title + '\n\n' + description

        # Sanity check.
        story = {
            'id': launchpad_id,
            'description': description,
            'created_at': created_at,
            'creator': owner,
            'is_bug': True,
            'title': title,
            'updated_at': updated_at,
            'tags': tags
        }
        duplicate = db_api.entity_get(Story, launchpad_id)
        if not duplicate:
            story = db_api.entity_create(Story, story)
        else:
            story = db_api.entity_update(Story, launchpad_id, story)

        # Duplicate check- launchpad import creates one task per story,
        # so if we already have a task on this story, skip it. This is to
        # properly replay imports in the case where errors occurred during
        # import.
        existing_task = db_api.model_query(Task) \
            .filter(Task.story_id == launchpad_id) \
            .first()
        if not existing_task:
            task = db_api.entity_create(Task, {
                'title': title,
                'assignee_id': assignee.id if assignee else None,
                'project_id': self.project.id,
                'story_id': launchpad_id,
                'created_at': created_at,
                'updated_at': updated_at,
                'priority': priority,
                'status': status
            })
        else:
            task = existing_task

        # Duplication Check - If this story already has a creation event,
        # we don't need to create a new one. Otherwise, create it manually so
        # we don't trigger event notifications.
        story_created_event = db_api.model_query(TimeLineEvent) \
            .filter(TimeLineEvent.story_id == launchpad_id) \
            .filter(TimeLineEvent.event_type == event_types.STORY_CREATED) \
            .first()
        if not story_created_event:
            db_api.entity_create(TimeLineEvent, {
                'story_id': launchpad_id,
                'author_id': owner.id,
                'event_type': event_types.STORY_CREATED,
                'created_at': created_at
            })

        # Create the creation event for the task, assuming it doesn't
        # exist yet.
        task_created_event = db_api.model_query(TimeLineEvent) \
            .filter(TimeLineEvent.story_id == launchpad_id) \
            .filter(TimeLineEvent.event_type == event_types.TASK_CREATED) \
            .first()
        if not task_created_event:
            db_api.entity_create(TimeLineEvent, {
                'story_id': launchpad_id,
                'author_id': owner.id,
                'event_type': event_types.TASK_CREATED,
                'created_at': created_at,
                'event_info': json.dumps({
                    'task_id': task.id,
                    'task_title': title
                })
            })

        # Create the discussion, loading any existing comments first.
        current_count = db_api.model_query(TimeLineEvent) \
            .filter(TimeLineEvent.story_id == launchpad_id) \
            .filter(TimeLineEvent.event_type == event_types.USER_COMMENT) \
            .count()
        desired_count = len(bug.messages)
        for i in range(current_count, desired_count):
            print '- Importing comment %s of %s' % (i + 1, desired_count)
            message = bug.messages[i]
            message_created_at = message.date_created \
                .strftime('%Y-%m-%d %H:%M:%S')
            message_owner = self.write_user(message.owner)

            comment = comments_api.comment_create({
                'content': message.content,
                'created_at': message_created_at
            })

            db_api.entity_create(TimeLineEvent, {
                'story_id': launchpad_id,
                'author_id': message_owner.id,
                'event_type': event_types.USER_COMMENT,
                'comment_id': comment.id,
                'created_at': message_created_at
            })

        return story